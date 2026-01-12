import calendar
import datetime
import logging
import os
import sys

import numpy as np
from osgeo import gdal  # type: ignore

MEDIA_FS = "/media/datastore"
TILES_PATH = MEDIA_FS + "/tempsreel.infoclimat.net/tiles"

# Logging configuration (minimal, only configure when module executed as script)
LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
LOG_DATEFMT = "%Y-%m-%d %H:%M:%S"
LOGGER = logging.getLogger(__name__)


def configure_logging(level: int = logging.INFO) -> None:
    """Configure logging with reasonable defaults.

    This function is intentionally not called at import time to avoid changing
    behavior for callers that import this module. Call it when executing as a
    script if logs are desired.
    """
    logging.basicConfig(
        level=level,
        format=LOG_FORMAT,
        datefmt=LOG_DATEFMT,
    )
    LOGGER.setLevel(level)


class CalcYearlyAcc:

    FILE_DIR = TILES_PATH
    """
    fichier geotiff de référence (valable en France de 2017-02-05 à NOW,
    sous réserve de changements futurs pour étendre le domaine radar à d'autres pays)
    """
    FILE_TEMPLATE = FILE_DIR + "/2018/01/01/ac60radaric_00_v00.tif"

    def datetime_to_filename(self, dt: datetime.datetime, key: str = "ac_yearly_radaricval") -> str:
        return f"{self.FILE_DIR}/{dt.year:04d}/{dt.month:02d}/{dt.day:02d}/{key}_{dt.hour:02d}_v{dt.minute:02d}.tif"

    def now(self) -> datetime.datetime:
        return datetime.datetime.now(datetime.UTC)

    def generate_yearly_accumulation_at_datetime(
        self,
        total_count: float,
        dh: datetime.datetime,
        end: datetime.datetime,
    ) -> None:
        out_file = self.datetime_to_filename(dh, "ac_yearly_radaricval")
        LOGGER.info(f"Creating accumulation file: {out_file}")

        fn = self.datetime_to_filename(dh, "ac60radaric")

        processed_until_now = (end - dh) / datetime.timedelta(hours=1)
        percent = (total_count - processed_until_now) / float(total_count) * 100.0
        LOGGER.info(f"[{percent:05.2f}%] processing file {fn}")
        if not os.path.isfile(fn):
            LOGGER.warning(f"File not found: '{fn}'\n")
            return
        h = gdal.Open(fn, gdal.GA_ReadOnly)
        if h is None:
            LOGGER.error(f"Failed to open file: '{fn}'\n")
            return

        # on remplace les NaN par des 0.0
        rr1h = h.ReadAsArray(0, 0, self.XPTS, self.YPTS)
        nb_valid_pixels = np.count_nonzero(~np.isnan(rr1h))

        # calculate accumulation in *10mm
        self.acc_beg_year += (np.nan_to_num(rr1h) * 10).astype(np.uint32)

        # @TODO do not add 1 in a pixel when rr1h is NoData (not possible currently because NoData==0.0, unless files error,
        # like /tiles/2018/09/29/ac60radaric_06_v00.tif which only contains NaNs)
        if nb_valid_pixels > 1000:
            self.nb_valid_values += self.MASK_ONES

        del h
        del rr1h

        # write accumulation
        dst_ds = gdal.GetDriverByName("GTiff").Create(
            out_file,
            self.XPTS,
            self.YPTS,
            2,
            gdal.GDT_UInt32,
            options=["COMPRESS=LZW", "PREDICTOR=2"],
        )
        dst_ds.GetRasterBand(1).WriteArray(self.acc_beg_year)
        dst_ds.GetRasterBand(1).SetNoDataValue(4294967295)
        dst_ds.GetRasterBand(2).WriteArray(self.nb_valid_values)
        dst_ds.GetRasterBand(2).SetNoDataValue(4294967295)
        dst_ds.SetGeoTransform(self.GEOT)
        dst_ds.SetProjection(self.PROJ)
        del dst_ds  # force writing to disk

        LOGGER.info(f"Wrote accumulation file: {out_file}\n")

    def execute(self) -> None:
        now = self.now()

        template_handler = gdal.Open(self.FILE_TEMPLATE, gdal.GA_ReadOnly)
        self.XPTS = template_handler.RasterXSize
        self.YPTS = template_handler.RasterYSize
        self.PROJ = template_handler.GetProjection()
        self.GEOT = template_handler.GetGeoTransform()
        del template_handler

        self.MASK_ONES = np.ones((self.YPTS, self.XPTS), dtype=np.uint32)

        self.acc_beg_year = np.zeros((self.YPTS, self.XPTS), dtype=np.uint32)
        self.nb_valid_values = np.zeros((self.YPTS, self.XPTS), dtype=np.uint32)

        year_to_compute = now.year
        if len(sys.argv) >= 2:
            arg = sys.argv[1]
            if arg != "latest" and arg.isdigit() and len(arg) == 4:
                year_to_compute = int(arg)

        nb_days_year = 365 + calendar.isleap(year_to_compute)

        # 01:00 le 1er jour de l'année Y
        first_file_of_the_year_datetime = datetime.datetime(
            year=year_to_compute,
            month=1,
            day=1,
            hour=1,
            minute=0,
            second=0,
            tzinfo=datetime.UTC,
        )

        start = first_file_of_the_year_datetime
        # 00:00 le 1er jour de l'année Y+1
        last_file_of_the_year_datetime = datetime.datetime(
            year=year_to_compute + 1,
            month=1,
            day=1,
            hour=0,
            minute=0,
            second=0,
            tzinfo=datetime.UTC,
        )

        end = min(last_file_of_the_year_datetime, now)

        if len(sys.argv) >= 2 and sys.argv[1] == "latest":
            # take last file from yesterday
            LOGGER.info("Finding last accumulation file...")
            min_hourly = now.replace(
                minute=0,
                second=0,
                microsecond=0,
                tzinfo=datetime.UTC,
            )
            tmp_dt = min_hourly
            while (
                not os.path.isfile(self.datetime_to_filename(tmp_dt, "ac_yearly_radaricval"))
                or os.path.getsize(self.datetime_to_filename(tmp_dt, "ac_yearly_radaricval")) < 10
            ):
                tmp_dt -= datetime.timedelta(hours=1)

            if tmp_dt < first_file_of_the_year_datetime:
                LOGGER.info(f"No accumulation file found for current year, starting from scratch.")
            else:
                begin_file = self.datetime_to_filename(tmp_dt, "ac_yearly_radaricval")
                LOGGER.info(f"Recovering from {begin_file}")

                # on remplace le cumul de départ
                fh_tmp = gdal.Open(begin_file, gdal.GA_ReadOnly)
                # bande 1 = accumulation
                self.acc_beg_year = fh_tmp.GetRasterBand(1).ReadAsArray(0, 0, self.XPTS, self.YPTS)
                # bande 2 = nb de valeurs valides
                self.nb_valid_values = fh_tmp.GetRasterBand(2).ReadAsArray(
                    0, 0, self.XPTS, self.YPTS
                )

                # on remplace le datetime de début pour commencer à l'heure suivante
                start = tmp_dt + datetime.timedelta(hours=1)

        total_count = (end - start) / datetime.timedelta(hours=1)
        dh = start
        while dh <= end:
            self.generate_yearly_accumulation_at_datetime(total_count, dh, end)
            dh += datetime.timedelta(hours=1)


class TestCalcYearlyAcc(CalcYearlyAcc):

    def __init__(self, now: datetime.datetime):
        self.fixed_now = now

    def now(self) -> datetime.datetime:
        return self.fixed_now


def main():
    calc_yearly_acc = CalcYearlyAcc()
    calc_yearly_acc.execute()


if __name__ == "__main__":
    configure_logging()
    main()
