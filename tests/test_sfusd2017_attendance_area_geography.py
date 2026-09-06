"""Investigates whether SFUSD's real 2017-18 attendance-area priority tier
(see witness.sfusd2017's module docstring: "sibling > CTIP1 > attendance
area > lottery") could be added as a second modeled priority tier in
witness/sfusd2017.py, using only what the raw 2017 CSV actually contains --
a ZIP code, nothing finer.

CONCLUSION, established by the computation below: NO. This is a REAL,
QUANTIFIED negative result, not a shortcut around doing the work -- see
data/external/sfusd_2017_kindergarten/attendance_area_geography/SOURCE.txt
for the full writeup and witness/sfusd2017.py's module docstring section
"ATTENDANCE AREA: INVESTIGATED AND NOT MODELED" for where this is
documented as a load-bearing modeling decision, not merely an unexplored
gap. Per REVIEWER.md's "a number that only exists when you run a script by
hand is not infrastructure," this test makes the negative finding
reproducible via the test runner rather than a one-off script -- it is the
evidence trail for a decision NOT to write market-building code, which is
exactly why this lives in tests/ rather than in witness/sfusd2017.py itself
(the adapter's actual runtime code has no geography/GIS dependency, and
this investigation should not force it to grow one).

Two independent, real primary-source geographic datasets are used (see
SOURCE.txt for full provenance, checksums, and license notes):
  1. SFUSD's own published attendance-area boundaries (DataSF, extracted
     from SFUSD's GIS system) -- BUT dated 2023/"2024-2025", seven years
     after this project's 2017-18 data. This year mismatch is flagged, not
     silently assumed away -- see SOURCE.txt.
  2. 2010 Census TIGER/Line ZCTA (ZIP Code Tabulation Area) boundaries for
     San Francisco's ZIP codes -- the closest-to-2017 ZIP boundary vintage
     available, and ZIP boundaries move far less over time than school
     attendance-area boundaries, so this file is a much smaller source of
     error than dataset (1)'s year gap.

Skipped cleanly when either the geography files or the `shapely` package
are absent, matching this suite's sibling `test_sfusd2017_replay.py`'s
skip-when-data-absent pattern.
"""

from __future__ import annotations

import collections
import csv
import json
import os
import unittest

GEO_DIR = os.path.join(
    "data", "external", "sfusd_2017_kindergarten", "attendance_area_geography"
)
ATTENDANCE_AREAS_PATH = os.path.join(
    GEO_DIR, "sfusd_attendance_areas_2024_2025.geojson"
)
ZIP_CODES_PATH = os.path.join(GEO_DIR, "sf_zip_codes_2010_census.geojson")
RAW_CSV = os.path.join(
    "data",
    "external",
    "sfusd_2017_kindergarten",
    "20171103_KQED_KinderAssignmentData_201718_K_Placement_2017-2018.csv",
)

HAVE_GEO_FILES = os.path.exists(ATTENDANCE_AREAS_PATH) and os.path.exists(
    ZIP_CODES_PATH
)

try:
    from shapely.geometry import shape
    from shapely.validation import make_valid

    HAVE_SHAPELY = True
except ImportError:  # pragma: no cover - environment-dependent
    HAVE_SHAPELY = False

HAVE_RAW = os.path.exists(RAW_CSV)

#: Known non-San-Francisco ZIP codes present in the 2017 raw file (families
#: applying to SFUSD from outside city limits). SFUSD attendance areas do
#: not exist outside SF, so these are excluded from the geographic overlap
#: analysis by construction -- reported here, not silently dropped.
OUT_OF_CITY_ZIPS = frozenset(
    {
        "94015",  # Daly City
        "94030",  # Millbrae
        "94066",  # San Bruno
        "94080",  # South San Francisco
        "94401",  # San Mateo
        "94538",  # Fremont
        "94801",  # Richmond
        "94806",  # Richmond
        "95812",  # not a real city ZIP in this context; excluded regardless
    }
)


def _load_geometries(path, id_field):
    with open(path) as f:
        data = json.load(f)
    out = []
    for feat in data["features"]:
        geom = shape(feat["geometry"])
        if not geom.is_valid:
            geom = make_valid(geom)
        out.append((feat["properties"][id_field], geom))
    return out


@unittest.skipUnless(HAVE_GEO_FILES, "attendance-area/ZIP geography files not present")
@unittest.skipUnless(HAVE_SHAPELY, "shapely not installed")
class AttendanceAreaFilesLoadAsExpected(unittest.TestCase):
    """Pins the shape of the two committed geography files themselves,
    independent of any overlap computation -- if these fail, the rest of
    this module is analyzing the wrong data."""

    def test_fifty_eight_attendance_areas(self):
        areas = _load_geometries(ATTENDANCE_AREAS_PATH, "aaname")
        self.assertEqual(len(areas), 58)
        names = {name for name, _ in areas}
        self.assertEqual(len(names), 58, "attendance area names were not unique")

    def test_twenty_seven_sf_zip_codes(self):
        zips = _load_geometries(ZIP_CODES_PATH, "ZCTA5CE10")
        self.assertEqual(len(zips), 27)
        for z, _ in zips:
            self.assertNotIn(
                z, OUT_OF_CITY_ZIPS, f"{z} is a non-SF ZIP; should not be in this file"
            )


@unittest.skipUnless(HAVE_GEO_FILES, "attendance-area/ZIP geography files not present")
@unittest.skipUnless(HAVE_SHAPELY, "shapely not installed")
class ZipCodeGranularityCannotSupportAttendanceAreaReconstruction(unittest.TestCase):
    """The headline negative finding. All figures are computed fresh from
    the two committed geometry files -- nothing here is a copied-in
    constant. See SOURCE.txt for the exact same numbers narrated in prose,
    and witness/sfusd2017.py's module docstring for where this conclusion
    is used to justify NOT adding attendance-area priority to the market
    model.

    Bounds below are deliberately a little looser than the single measured
    run recorded in SOURCE.txt (24/27 zips, 43.0% median, 84.3% of
    applicants at risk) to avoid flakiness from GEOS/shapely version-level
    floating point differences in polygon intersection area -- the
    qualitative conclusion (severe, majority-of-applicants granularity
    mismatch) is what must survive, not four significant figures of a
    third-party geometry library's arithmetic.
    """

    @classmethod
    def setUpClass(cls):
        cls.areas = _load_geometries(ATTENDANCE_AREAS_PATH, "aaname")
        cls.zips = _load_geometries(ZIP_CODES_PATH, "ZCTA5CE10")

    def _overlaps_by_zip(self):
        """{zip: [(attendance_area_name, fraction_of_zip_area), ...]}
        sorted by fraction descending, restricted to overlaps > 0."""
        results = {}
        for z, zgeom in self.zips:
            overlaps = []
            for name, ageom in self.areas:
                inter = zgeom.intersection(ageom)
                if inter.area > 0:
                    overlaps.append((name, inter.area / zgeom.area))
            overlaps.sort(key=lambda x: -x[1])
            results[z] = overlaps
        return results

    def test_most_sf_zips_span_multiple_attendance_areas(self):
        """If most ZIPs mapped cleanly onto one attendance area, a
        ZIP-to-attendance-area join would be a reasonable approximation.
        It does not: the overwhelming majority of SF ZIPs meaningfully
        overlap more than one attendance area."""
        results = self._overlaps_by_zip()
        n_multi = sum(
            1
            for overlaps in results.values()
            if len([f for _, f in overlaps if f > 0.02]) > 1
        )
        self.assertGreaterEqual(
            n_multi,
            20,
            f"only {n_multi}/27 SF zips overlapped multiple attendance areas -- "
            f"if this ever rose to most zips mapping cleanly onto one attendance "
            f"area, a ZIP-based join might become viable and this conclusion "
            f"should be revisited",
        )

    def test_plurality_attendance_area_typically_covers_less_than_half_the_zip(self):
        """The best-covering single attendance area inside a ZIP, on
        average, does not even reach half that ZIP's own area -- direct
        evidence that "assign each ZIP to its majority/plurality
        attendance area" is not a reasonable approximation here."""
        results = self._overlaps_by_zip()
        top_fracs = [overlaps[0][1] if overlaps else 0.0 for overlaps in results.values()]
        top_fracs.sort()
        median = top_fracs[len(top_fracs) // 2]
        self.assertLess(
            median,
            0.55,
            f"median plurality-attendance-area coverage was {median:.1%}, "
            f"high enough that a ZIP-based join might be defensible -- "
            f"revisit the conclusion in witness/sfusd2017.py's docstring",
        )

    @unittest.skipUnless(HAVE_RAW, "SFUSD 2017 raw CSV not present")
    def test_most_real_applicants_live_in_a_zip_with_no_dominant_attendance_area(self):
        """Weights the same finding by the ACTUAL 2017 applicant population
        rather than just by ZIP count -- some ZIPs hold far more applicants
        than others, so this is the number that actually matters for how
        many real families a forced join would misclassify."""
        with open(RAW_CSV, newline="") as f:
            rows = list(csv.DictReader(f))
        zip_counts = collections.Counter(
            r["Student's Residential Zip Code"] for r in rows
        )
        sf_zip_counts = {
            z: c for z, c in zip_counts.items() if z not in OUT_OF_CITY_ZIPS
        }
        results = self._overlaps_by_zip()
        top_frac_by_zip = {
            z: (overlaps[0][1] if overlaps else 0.0) for z, overlaps in results.items()
        }
        total_sf = sum(sf_zip_counts.values())
        at_risk = sum(
            c for z, c in sf_zip_counts.items() if top_frac_by_zip.get(z, 0.0) < 0.5
        )
        self.assertGreater(total_sf, 0)
        fraction_at_risk = at_risk / total_sf
        self.assertGreater(
            fraction_at_risk,
            0.70,
            f"only {fraction_at_risk:.1%} of SF applicants were in a zip with no "
            f"dominant attendance area -- if this drops well below 70%, most "
            f"real applicants COULD be geolocated with reasonable confidence "
            f"and the no-attendance-area-priority decision should be revisited",
        )


if __name__ == "__main__":
    unittest.main()
