"""Read-only UI cache around the unchanged production scorer."""
from hashlib import sha256
from pathlib import Path
import streamlit as st
import numpy as np

MARKETS = ('fouls', 'corners', 'yellow_cards')


def input_version(base):
    base = Path(base)
    models = [base / 'models' / f'{m}_model.joblib' for m in MARKETS]
    missing = [p.name for p in models if not p.is_file()]
    if missing:
        raise FileNotFoundError('Chybějí modelové artefakty: ' + ', '.join(missing))
    # Include optional files as well: their arrival/removal invalidates the cache.
    paths = models + [base / 'data' / 'tables' / name for name in
                     ('team_match_stats.csv', 'referee_match_stats.csv')]
    paths += sorted((base / 'data' / 'fixtures').glob('*.csv'))
    paths += [base / 'models' / f'{m}_model_metadata.json' for m in MARKETS]
    paths += [base / 'app' / 'model_loading.py']
    paths += sorted((base / 'config').glob('*_model.json'))
    paths += [base / 'scripts' / name for name in
              ('score_round.py', 'fixture_features.py', 'count_common.py')]
    return tuple((str(p.relative_to(base)), sha256(p.read_bytes()).hexdigest() if p.exists() else None)
                 for p in paths)


@st.cache_data(show_spinner=False, max_entries=32)
def cached_analysis(base, version, home, away, match_date, season, referee):
    from score_round import score_fixtures
    # Check again on a cache miss before the scorer opens the same files.
    if input_version(base) != version:
        raise ValueError('Vstupní data se během analýzy změnila. Zkus znovu načíst stránku.')
    from app.model_loading import validate_models
    provenance = validate_models(base)
    result = score_fixtures([dict(home_team=home, away_team=away, match_date=str(match_date),
                                  season=season, referee=referee)])
    if result.empty or not np.isfinite(result['prediction']).all() or (result['prediction'] < 0).any():
        raise ValueError('Model vrátil neplatnou predikci.')
    for column in ('p_over', 'p_under'):
        if column in result and not result[column].between(0, 1).all():
            raise ValueError('Model vrátil neplatnou pravděpodobnost.')
    if {'p_over', 'p_under'} <= set(result) and not np.allclose(result.p_over + result.p_under, 1):
        raise ValueError('Pravděpodobnosti over/under nejsou konzistentní.')
    if input_version(base) != version:
        raise ValueError('Vstupní data se během analýzy změnila. Výsledek nebyl uložen do cache.')
    result.attrs['model_provenance'] = provenance
    return result


def analyze(base, home, away, match_date, season, referee):
    version = input_version(base)
    result = cached_analysis(str(base), version, home, away, str(match_date), season, referee)
    if input_version(base) != version:
        raise ValueError('Vstupní data se během analýzy změnila. Zkus znovu načíst stránku.')
    return result, version
