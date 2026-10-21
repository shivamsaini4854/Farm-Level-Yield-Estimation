"""Repository paths are independent of the process working directory."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW_DATA = ROOT / 'data' / 'raw'
NDVI_RAW = RAW_DATA / 'ndvi'
PROCESSED_DATA = ROOT / 'data' / 'processed'
GEO_DATA = ROOT / 'data' / 'geo'
ARTIFACTS = ROOT / 'artifacts'
BASELINE = ARTIFACTS / 'baseline' / 'legacy'
RUNS = ARTIFACTS / 'runs'
CURRENT = ARTIFACTS / 'current.json'
ENV_FILE = ROOT / '.env'
CERTIFICATE = ROOT / 'certs' / 'isrgrootx1.pem'
