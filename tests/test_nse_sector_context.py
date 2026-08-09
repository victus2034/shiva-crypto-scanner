import unittest

import pandas as pd

import nse_scanner


class NseSectorContextTests(unittest.TestCase):
    def test_constituent_sector_map_covers_all_rows(self):
        csv = pd.DataFrame(
            [
                {"Symbol": "HDFCBANK", "Industry": "Financial Services"},
                {"Symbol": "INFY", "Industry": "Information Technology"},
                {"Symbol": "SUNPHARMA", "Industry": "Healthcare"},
                {"Symbol": "MARUTI", "Industry": "Automobile and Auto Components"},
                {"Symbol": "RELIANCE", "Industry": "Oil Gas & Consumable Fuels"},
                {"Symbol": "GRASIM", "Industry": "Construction Materials"},
                {"Symbol": "TRENT", "Industry": "Consumer Services"},
                {"Symbol": "UNKNOWN", "Industry": "New Industry Name"},
            ]
        )

        sector_map = nse_scanner.build_sector_map_from_constituents(csv)

        self.assertEqual(set(sector_map), {f"{item}.NS" for item in csv["Symbol"]})
        self.assertEqual(sector_map["HDFCBANK.NS"], "Financials")
        self.assertEqual(sector_map["INFY.NS"], "Technology & Telecom")
        self.assertEqual(sector_map["UNKNOWN.NS"], "Unclassified")

    def test_sector_context_uses_median_session_move(self):
        nse_scanner.NSE_SECTOR_MAP = {
            "AAA.NS": "Technology & Telecom",
            "BBB.NS": "Technology & Telecom",
            "CCC.NS": "Financials",
        }
        nse_scanner.MARKET_DATA = {
            "AAA.NS": pd.DataFrame(
                {
                    "Datetime": pd.to_datetime(["2026-08-10 09:15", "2026-08-10 10:15"]),
                    "open": [100.0, 101.0],
                    "close": [100.5, 102.0],
                }
            ),
            "BBB.NS": pd.DataFrame(
                {
                    "Datetime": pd.to_datetime(["2026-08-10 09:15", "2026-08-10 10:15"]),
                    "open": [200.0, 202.0],
                    "close": [201.0, 206.0],
                }
            ),
            "CCC.NS": pd.DataFrame(
                {
                    "Datetime": pd.to_datetime(["2026-08-10 09:15", "2026-08-10 10:15"]),
                    "open": [50.0, 49.0],
                    "close": [49.5, 48.0],
                }
            ),
        }

        context = nse_scanner.build_sector_context(["AAA.NS", "BBB.NS", "CCC.NS"])

        self.assertAlmostEqual(context["Technology & Telecom"]["session_pct"], 2.5)
        self.assertEqual(context["Technology & Telecom"]["members"], 2)
        self.assertAlmostEqual(context["Financials"]["session_pct"], -4.0)


if __name__ == "__main__":
    unittest.main()
