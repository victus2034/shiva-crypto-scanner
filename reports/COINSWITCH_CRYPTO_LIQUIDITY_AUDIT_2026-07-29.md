# CoinSwitch Crypto Futures Liquidity Audit

Audit date: 2026-07-29

Snapshot time: approximately 13:01 IST

Intended use: select CoinSwitch-available crypto perpetuals for both the 30m and 4h production scanners without changing indicator, rating, alert, Discord, or scheduler behavior.

## Decision

- CoinSwitch crypto futures inspected: 503
- Minimum liquidity: USD 3,000,000 in displayed 24h USDT volume
- Contracts meeting the threshold: 98
- Excluded ticker collision: SLX crypto, because `SLX/USDT:USDT` is already used for the US-stock contract
- Final production crypto universe: 97
- Existing liquid crypto symbols retained: 44
- New liquid crypto symbols added: 53
- Non-crypto and xStock contracts preserved: 39

The USD 3M threshold was selected because it is the clean cutoff nearest the requested 100-contract target. A USD 2M threshold would include 123 contracts, while USD 4M would include 84.

## Verification

- All 97 production crypto symbols resolved through at least one configured futures exchange.
- All eight configured public exchange market catalogs loaded successfully.
- 30m candle checks: 97/97 passed.
- 4h candle checks: 97/97 passed.
- Combined no-alert candle checks: 194/194 passed.
- No Discord webhook was invoked during the dry-run.

## Production Crypto Universe

| Rank | CoinSwitch pair | Scanner symbol | 24h USDT volume |
| ---: | --- | --- | ---: |
| 1 | BTC/USDT | BTCUSD | 3.89B |
| 2 | ETH/USDT | ETHUSD | 2.75B |
| 3 | SOL/USDT | SOLUSD | 379.21M |
| 4 | BANK/USDT | BANK/USDT | 247.86M |
| 5 | XRP/USDT | XRPUSD | 190.55M |
| 6 | HYPE/USDT | HYPEUSD | 153.05M |
| 7 | AKE/USDT | AKE/USDT | 88.01M |
| 8 | COTI/USDT | COTI/USDT | 86.41M |
| 9 | ZEC/USDT | ZECUSD | 79.82M |
| 10 | DOGE/USDT | DOGEUSD | 73.37M |
| 11 | ADA/USDT | ADAUSD | 60.62M |
| 12 | NEAR/USDT | NEARUSD | 60.20M |
| 13 | DEXE/USDT | DEXE/USDT | 51.89M |
| 14 | 1000PEPE/USDT | 1000PEPEUSD | 49.09M |
| 15 | ONDO/USDT | ONDOUSD | 45.78M |
| 16 | SOON/USDT | SOON/USDT | 39.68M |
| 17 | AAVE/USDT | AAVEUSD | 38.20M |
| 18 | WLD/USDT | WLD/USDT | 38.19M |
| 19 | KAITO/USDT | KAITO/USDT | 37.81M |
| 20 | PUMPFUN/USDT | PUMPUSD | 35.72M |
| 21 | BEAT/USDT | BEAT/USDT | 35.27M |
| 22 | SUI/USDT | SUIUSD | 31.92M |
| 23 | ENA/USDT | ENA/USDT | 31.62M |
| 24 | EUL/USDT | EUL/USDT | 31.18M |
| 25 | ZIL/USDT | ZIL/USDT | 26.36M |
| 26 | UNI/USDT | UNIUSD | 24.85M |
| 27 | LINK/USDT | LINKUSD | 24.04M |
| 28 | TAO/USDT | TAO/USDT | 22.17M |
| 29 | AVAX/USDT | AVAXUSD | 22.08M |
| 30 | SHIB1000/USDT | 1000SHIBUSD | 22.02M |
| 31 | LTC/USDT | LTCUSD | 21.60M |
| 32 | BTW/USDT | BTW/USDT | 21.33M |
| 33 | VANRY/USDT | VANRY/USDT | 20.81M |
| 34 | LA/USDT | LA/USDT | 20.44M |
| 35 | BNB/USDT | BNBUSD | 19.33M |
| 36 | OP/USDT | OPUSD | 18.88M |
| 37 | INJ/USDT | INJUSD | 17.52M |
| 38 | FARTCOIN/USDT | FARTCOIN/USDT | 16.12M |
| 39 | GRAM/USDT | GRAMUSD | 13.99M |
| 40 | XPL/USDT | XPLUSD | 13.36M |
| 41 | ESPORTS/USDT | ESPORTS/USDT | 12.55M |
| 42 | XLM/USDT | XLM/USDT | 12.11M |
| 43 | ASTER/USDT | ASTER/USDT | 12.08M |
| 44 | ZAMA/USDT | ZAMA/USDT | 11.91M |
| 45 | XMR/USDT | XMRUSD | 11.27M |
| 46 | TRUMP/USDT | TRUMP/USDT | 11.25M |
| 47 | ARB/USDT | ARBUSD | 11.25M |
| 48 | WIF/USDT | WIF/USDT | 11.15M |
| 49 | ESP/USDT | ESP/USDT | 10.06M |
| 50 | LDO/USDT | LDO/USDT | 9.70M |
| 51 | APT/USDT | APTUSD | 9.53M |
| 52 | PENGU/USDT | PENGU/USDT | 9.27M |
| 53 | 1000BONK/USDT | 1000BONKUSD | 9.25M |
| 54 | BCH/USDT | BCHUSD | 9.03M |
| 55 | DOT/USDT | DOTUSD | 8.82M |
| 56 | UB/USDT | UB/USDT | 8.12M |
| 57 | ZRO/USDT | ZRO/USDT | 7.30M |
| 58 | VVV/USDT | VVV/USDT | 7.30M |
| 59 | ATOM/USDT | ATOM/USDT | 7.19M |
| 60 | AERO/USDT | AERO/USDT | 7.13M |
| 61 | TRX/USDT | TRX/USDT | 6.68M |
| 62 | ALLO/USDT | ALLO/USDT | 6.67M |
| 63 | SEI/USDT | SEIUSD | 6.50M |
| 64 | CAP/USDT | CAP/USDT | 6.41M |
| 65 | RE/USDT | RE/USDT | 6.03M |
| 66 | PHAROS/USDT | PHAROS/USDT | 5.80M |
| 67 | VIRTUAL/USDT | VIRTUAL/USDT | 5.55M |
| 68 | FIL/USDT | FILUSD | 5.36M |
| 69 | US/USDT | US/USDT | 5.33M |
| 70 | HBAR/USDT | HBAR/USDT | 5.21M |
| 71 | ICP/USDT | ICP/USDT | 5.19M |
| 72 | BOME/USDT | BOME/USDT | 5.06M |
| 73 | ORDI/USDT | ORDI/USDT | 4.93M |
| 74 | COAI/USDT | COAI/USDT | 4.92M |
| 75 | TAIKO/USDT | TAIKO/USDT | 4.87M |
| 76 | TIA/USDT | TIAUSD | 4.79M |
| 77 | WLFI/USDT | WLFI/USDT | 4.70M |
| 78 | LAB/USDT | LABUSD | 4.62M |
| 79 | JUP/USDT | JUP/USDT | 4.62M |
| 80 | O/USDT | O/USDT | 4.30M |
| 81 | JTO/USDT | JTO/USDT | 4.24M |
| 82 | MNT/USDT | MNT/USDT | 4.21M |
| 83 | STRK/USDT | STRK/USDT | 4.13M |
| 84 | ERA/USDT | ERA/USDT | 3.92M |
| 85 | CRV/USDT | CRV/USDT | 3.77M |
| 86 | MMT/USDT | MMT/USDT | 3.75M |
| 87 | STORJ/USDT | STORJ/USDT | 3.71M |
| 88 | ALGO/USDT | ALGO/USDT | 3.65M |
| 89 | ETHFI/USDT | ETHFI/USDT | 3.63M |
| 90 | DASH/USDT | DASH/USDT | 3.56M |
| 91 | GALA/USDT | GALA/USDT | 3.55M |
| 92 | PEOPLE/USDT | PEOPLE/USDT | 3.49M |
| 93 | 0G/USDT | 0G/USDT | 3.40M |
| 94 | HOME/USDT | HOME/USDT | 3.38M |
| 95 | POL/USDT | POL/USDT | 3.33M |
| 96 | KGEN/USDT | KGEN/USDT | 3.22M |
| 97 | GWEI/USDT | GWEI/USDT | 3.02M |

## Removed Existing Crypto Contracts

Below the USD 3M threshold:

| Scanner symbol | CoinSwitch 24h USDT volume |
| --- | ---: |
| ETCUSD | 2.96M |
| EVAAUSD | 2.03M |
| BILLUSD | 1.97M |
| RIVERUSD | 1.31M |
| VELVET/USDT | 1.21M |
| T/USDT | 1.01M |
| MUSD | 959.72K |
| TRIA/USDT | 770.42K |
| MAGMA/USDT | 450.20K |
| SXT/USDT | 353.12K |
| CVX/USDT:USDT | 309.15K |
| THE/USDT | 123.39K |

Not present in the CoinSwitch Crypto futures category at audit time:

- FET/USDT
- DODO/USDT
- AIOTUSD
- SYN/USDT
- LIT/USDT
- RIF/USDT

## Operational Notes

- Volume is a point-in-time 24h snapshot and can change materially.
- Re-run this audit periodically before keeping borderline contracts.
- Existing scanner symbols were retained where possible so persisted alert cooldown keys remain stable.
- This audit checks CoinSwitch listing and displayed turnover, not order-book depth, bid-ask spread, or executable slippage.
