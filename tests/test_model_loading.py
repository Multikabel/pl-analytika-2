import json
import runpy
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import joblib
import pytest

from app.model_loading import validate_models, MARKETS


@pytest.fixture
def bundle(tmp_path):
    (tmp_path / 'models').mkdir()
    (tmp_path / 'config').mkdir()
    for market in MARKETS:
        cfg = dict(features=['a', 'b'])
        meta = dict(market=market, config=cfg, trained_at='2026-10-10T01:25:08',
                    trained_rows=3140, seasons=['2026-27'], train_mean=10.)
        (tmp_path / 'config' / f'{market}_model.json').write_text(json.dumps(cfg))
        (tmp_path / 'models' / f'{market}_model_metadata.json').write_text(json.dumps(meta))
        joblib.dump(dict(meta, model=SimpleNamespace(feature_names_in_=['a', 'b'])),
                    tmp_path / 'models' / f'{market}_model.joblib')
    return tmp_path


def test_startup_does_not_train_or_write():
    root = Path(__file__).resolve().parents[1]
    with patch('runpy.run_path') as run, patch('subprocess.run') as train:
        exec(compile((root / 'streamlit_app.py').read_text(), 'entrypoint', 'exec'),
             {'__file__': str(root / 'streamlit_app.py')})
        run.assert_called_once()
        train.assert_not_called()


def test_valid_artifacts_disclose_unverified_freshness(bundle):
    notices = validate_models(bundle)
    assert len(notices) == 3
    assert all('3140' in n and '2026-10-10' in n and 'nejsou doloženy' in n for n in notices)


@pytest.mark.parametrize('failure', ['missing', 'all_missing', 'metadata', 'corrupt',
                                   'features', 'metadata_conflict', 'hash', 'config'])
def test_fail_closed_without_writes(bundle, failure):
    model = bundle / 'models/fouls_model.joblib'
    meta = bundle / 'models/fouls_model_metadata.json'
    if failure == 'missing': model.unlink()
    elif failure == 'all_missing':
        for p in (bundle / 'models').glob('*.joblib'): p.unlink()
    elif failure == 'metadata': meta.unlink()
    elif failure == 'corrupt': model.write_bytes(b'broken')
    elif failure == 'features':
        art = joblib.load(model); art['model'].feature_names_in_ = ['b', 'a']; joblib.dump(art, model)
    elif failure == 'config':
        (bundle / 'config/fouls_model.json').write_text('{"features":["different"]}')
    else:
        data = json.loads(meta.read_text())
        data['model_sha256' if failure == 'hash' else 'trained_rows'] = 'wrong'
        meta.write_text(json.dumps(data))
    before = {str(p): p.read_bytes() for p in bundle.rglob('*') if p.is_file()}
    with pytest.raises((ValueError, FileNotFoundError)):
        validate_models(bundle)
    assert before == {str(p): p.read_bytes() for p in bundle.rglob('*') if p.is_file()}


def test_metadata_changes_invalidate_cache(bundle):
    from app.match_analysis import input_version
    before = input_version(bundle)
    meta = bundle / 'models/fouls_model_metadata.json'
    meta.write_text(meta.read_text() + ' ')
    assert input_version(bundle) != before
