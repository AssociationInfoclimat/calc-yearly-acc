from osgeo import gdal
import numpy as np
import datetime
import calendar
import os
import sys

MEDIA_FS = "/media/datastore"
TILES_PATH = MEDIA_FS + "/tempsreel.infoclimat.net/tiles"


class CalcYearlyAcc:

    FILE_DIR = TILES_PATH
    """
    fichier geotiff de référence (valable en France de 2017-02-05 à NOW,
    sous réserve de changements futurs pour étendre le domaine radar à d'autres pays)
    """
    FILE_TEMPLATE = FILE_DIR + "/2018/01/01/ac60radaric_00_v00.tif"

    def datetime_to_filename(self, dt: datetime.datetime, key: str = "ac_yearly_radaricval") -> str:
        return f"{self.FILE_DIR}/{dt.year:04d}/{dt.month:02d}/{dt.day:02d}/{key}_{dt.hour:02d}_v{dt.minute:02d}.tif"

    def generate_yearly_accumulation_at_datetime(
        self,
        total_count: float,
        dh: datetime.datetime,
        end: datetime.datetime,
    ) -> None:
        fn = self.datetime_to_filename(dh, "ac60radaric")

        processed_until_now = (end - dh) / datetime.timedelta(hours=1)
        percent = (total_count - processed_until_now) / float(total_count) * 100.0
        print(f"[{percent:05.2f}%] {fn}")
        if not os.path.isfile(fn):
            print(f" >> NOT FOUND : '{fn}'")
            return
        h = gdal.Open(fn, gdal.GA_ReadOnly)
        if h is None:
            print(f" >> NOT OPENED : '{fn}'")
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
        outFile = self.datetime_to_filename(dh, "ac_yearly_radaricval")
        dst_ds = gdal.GetDriverByName("GTiff").Create(
            outFile,
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
        print(" >> OK")

    def execute(self) -> None:
        YEAR = datetime.datetime.now(datetime.UTC).year

        template_handler = gdal.Open(self.FILE_TEMPLATE, gdal.GA_ReadOnly)
        self.XPTS = template_handler.RasterXSize
        self.YPTS = template_handler.RasterYSize
        self.PROJ = template_handler.GetProjection()
        self.GEOT = template_handler.GetGeoTransform()
        del template_handler

        self.MASK_ONES = np.ones((self.YPTS, self.XPTS), dtype=np.uint32)

        self.acc_beg_year = np.zeros((self.YPTS, self.XPTS), dtype=np.uint32)
        self.nb_valid_values = np.zeros((self.YPTS, self.XPTS), dtype=np.uint32)
        nb_days_year = 365 + calendar.isleap(YEAR)

        # 01:00 le 1er jour de l'année Y
        start = datetime.datetime(
            year=YEAR,
            month=1,
            day=1,
            hour=1,
            minute=0,
            second=0,
            tzinfo=datetime.UTC,
        )
        # 00:00 le 1er jour de l'année Y+1
        end = datetime.datetime(
            year=YEAR + 1,
            month=1,
            day=1,
            hour=0,
            minute=0,
            second=0,
            tzinfo=datetime.UTC,
        )
        now = datetime.datetime.now(datetime.UTC)

        if len(sys.argv) >= 2 and sys.argv[1] == "latest":
            # take last file from yesterday
            print("Finding last accumulation file...")
            min_hourly = datetime.datetime.now(datetime.UTC).replace(
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

            begin_file = self.datetime_to_filename(tmp_dt, "ac_yearly_radaricval")
            print(f"Recovering from {begin_file}")

            # on remplace le cumul de départ
            fh_tmp = gdal.Open(begin_file, gdal.GA_ReadOnly)
            # bande 1 = accumulation
            self.acc_beg_year = fh_tmp.GetRasterBand(1).ReadAsArray(0, 0, self.XPTS, self.YPTS)
            # bande 2 = nb de valeurs valides
            self.nb_valid_values = fh_tmp.GetRasterBand(2).ReadAsArray(0, 0, self.XPTS, self.YPTS)

            # on remplace le datetime de début pour commencer à l'heure suivante
            start = tmp_dt + datetime.timedelta(hours=1)

        total_count = (end - start) / datetime.timedelta(hours=1)
        dh = start
        while dh <= end and dh <= now:
            self.generate_yearly_accumulation_at_datetime(total_count, dh, end)
            dh += datetime.timedelta(hours=1)

        if dh > now:
            print("IN THE FUTURE", dh, now)


def main():
    calc_yearly_acc = CalcYearlyAcc()
    calc_yearly_acc.execute()


if __name__ == "__main__":
    main()
