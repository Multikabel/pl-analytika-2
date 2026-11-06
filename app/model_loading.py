"""Read-only preflight for locally provisioned, trusted joblib artifacts.

Joblib is executable serialization: this is compatibility/integrity validation,
not a sandbox for untrusted downloads. No downloads or repairs occur here.
"""
from pathlib import Path
from hashlib import sha256
import json
import math
import warnings
from datetime import datetime

import joblib
from sklearn.exceptions import InconsistentVersionWarning

MARKETS = ('fouls', 'corners', 'yellow_cards')


def validate_models(base):
    base = Path(base)
    notices = []
    for market in MARKETS:
        path = base / 'models' / f'{market}_model.joblib'
        meta_path = path.with_name(f'{market}_model_metadata.json')
        if not path.is_file() or not meta_path.is_file():
            raise FileNotFoundError(f'Nedostupný model nebo metadata: {market}')
        try:
            meta = json.loads(meta_path.read_text(encoding='utf-8'))
            digest = sha256(path.read_bytes()).hexdigest()
            if meta.get('model_sha256') and meta['model_sha256'] != digest:
                raise ValueError('Neshodný SHA256 modelu')
            with warnings.catch_warnings():
                warnings.simplefilter('error', InconsistentVersionWarning)
                artifact = joblib.load(path)
            config = json.loads((base / 'config' / f'{market}_model.json').read_text(encoding='utf-8'))
            if artifact['market'] != market or artifact['config'] != config:
                raise ValueError('Nekompatibilní trh nebo konfigurace')
            features = config['features']
            if not features or len(set(features)) != len(features):
                raise ValueError('Neplatný seznam features')
            if list(artifact['model'].feature_names_in_) != features:
                raise ValueError('Nekompatibilní názvy nebo pořadí features')
            for key in ('market', 'config', 'train_mean', 'trained_rows', 'seasons', 'trained_at'):
                if artifact[key] != meta[key]:
                    raise ValueError(f'Metadata neodpovídají modelu: {key}')
            trained = datetime.fromisoformat(meta['trained_at'])
            if not math.isfinite(float(meta['train_mean'])) or float(meta['train_mean']) < 0:
                raise ValueError('Neplatný trénovací průměr')
            if not isinstance(meta['trained_rows'], int) or meta['trained_rows'] <= 0:
                raise ValueError('Neplatný počet trénovacích řádků')
            notices.append(
                f"{market}: lokální model, trénován {trained.isoformat()}, "
                f"{meta['trained_rows']} řádků. SHA256 {digest}. "
                'Aktuálnost vůči dnešním datům ani produkční původ nejsou doloženy.'
            )
        except Exception as exc:
            # Deserialization may raise many library-specific errors. Fail closed;
            # the UI keeps other pages available and never retrains on failure.
            raise ValueError(f'Model {market} nelze bezpečně použít: {exc}') from exc
    return notices
