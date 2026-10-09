"""Offline production-path checks; no network or production cache writes."""
import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

import pandas as pd
import requests
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import update_officials as officials
import auto_update

FIXTURES = Path(__file__).parent / 'fixtures' / 'officials'
EXPECTED = {
    ('Arsenal','Leeds'): 'P Tierney',
    ('Aston Villa','Brentford'): 'C Pawson',
    ('Chelsea','Bournemouth'): 'S Barrott',
    ('Ipswich','Fulham'): 'L Smith',
    ('Sunderland','Brighton & Hove Albion'): 'T Bramall',
    ('Manchester United','Tottenham'): 'S Attwell',
    ('Crystal Palace','Nottingham Forest'): 'P Bankes',
    ('Hull','Everton'): 'M Salisbury',
    ('Liverpool','Manchester City'): 'C Kavanagh',
    ('Coventry','Newcastle United'): 'J Brooks',
}


class OfficialsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.html = (FIXTURES / 'mw6.html').read_text(encoding='utf-8')
        self.matches = json.loads((FIXTURES / 'mw6_matches.json').read_text())
        pd.DataFrame([dict(season='2026-27',match_round=6,home_team=h,away_team=a)
                      for h,a in EXPECTED]).to_csv(self.base/'premier_league_2026-27.csv',index=False)
        self.enterContext(patch.object(officials, 'FIXTURE_DIR', self.base))
        self.enterContext(patch.object(officials, 'CACHE', self.base/'cache.csv'))
        self.enterContext(patch.object(officials, 'KNOWN_APPOINTMENTS', {}))
        self.net = self.enterContext(patch.object(officials.requests, 'get', side_effect=self.response))
        self.enterContext(contextlib.redirect_stdout(io.StringIO()))

    def response(self, url, **kwargs):
        if url.startswith(officials.MATCH_API):
            return Mock(json=Mock(return_value=self.matches[url.rsplit('/',1)[-1]]),
                        raise_for_status=Mock())
        if url == officials.CONTENT_API:
            return Mock(json=Mock(return_value={'content':[dict(id=4729629,
                title='Match officials for Matchweek 6', description='2026/27 fixtures')]}),
                raise_for_status=Mock())
        if '/news/4729629/' in url:
            return Mock(text=self.html, raise_for_status=Mock())
        raise AssertionError('Unexpected URL: '+url)

    def appointments(self, rows):
        return {(r.home_team,r.away_team):r.referee for r in rows.itertuples()}

    def sync(self):
        return officials.sync_officials(6, force=True)

    def remove_one(self):
        self.html = self.html.replace('Paul Tierney.', '', 1)

    def test_complete_mw6_real_article(self):
        result = self.sync()
        self.assertEqual(EXPECTED, self.appointments(result))
        self.assertEqual('complete', result.attrs['officials_report']['status'])
        self.assertEqual(10, len(pd.read_csv(officials.CACHE)))

    def test_reordered_cards_do_not_change_mapping(self):
        soup = BeautifulSoup(self.html, 'html.parser')
        cards = soup.select('[data-match-reference]')
        blocks = [(str(c.parent), str(c.parent.find_next_sibling('p'))) for c in cards]
        self.html = '<article><h1>Match officials for Matchweek 6</h1><p>2026/27</p>' + ''.join(
            card+paragraph for card,paragraph in reversed(blocks)) + '</article>'
        self.assertEqual(EXPECTED, self.appointments(self.sync()))

    def test_missing_referee_saves_only_verified_nine_and_fails(self):
        self.remove_one()
        result = self.sync()
        self.assertEqual(9,len(result))
        self.assertEqual([('Arsenal','Leeds')],result.attrs['officials_report']['missing'])
        self.assertEqual('published_import_failed',result.attrs['officials_report']['status'])

    def test_duplicate_appointment_is_not_silently_deduplicated(self):
        self.html = self.html.replace('</article>',
            '<div data-match-reference="2645245"></div><p>Referee: Paul Tierney.</p></article>')
        result = self.sync()
        self.assertEqual(9,len(result))
        self.assertNotIn(('Arsenal','Leeds'),self.appointments(result))
        self.assertEqual('published_import_failed',result.attrs['officials_report']['status'])

    def test_no_positional_fallback(self):
        soup = BeautifulSoup(self.html,'html.parser')
        for card in soup.select('[data-match-reference]'): card.decompose()
        self.html = str(soup)
        self.assertEqual(0,len(self.sync()))
        self.assertFalse(officials.CACHE.exists())

    def test_var_is_not_a_referee(self):
        self.html = self.html.replace('Referee: </strong>Paul Tierney.', 'VAR: </strong>Paul Tierney.',1)
        self.assertNotIn(('Arsenal','Leeds'), self.appointments(self.sync()))

    def test_wrong_season_match_rejected(self):
        self.matches['2645245']['seasonId'] = '2025'
        self.assertNotIn(('Arsenal','Leeds'),self.appointments(self.sync()))

    def test_wrong_fixture_rejected(self):
        self.matches['2645245']['awayTeam']['name'] = 'Chelsea'
        self.assertEqual(9,len(self.sync()))

    def test_wrong_article_season_rejected(self):
        self.html = self.html.replace('2026/27','2025/26')
        self.assertEqual(0,len(self.sync()))

    def test_unavailable_known_article_preserves_cache_bytes(self):
        result = self.sync()
        before = officials.CACHE.read_bytes()
        self.net.side_effect = requests.ConnectionError('offline')
        result = self.sync()
        self.assertEqual(before,officials.CACHE.read_bytes())
        self.assertEqual(EXPECTED,self.appointments(result))
        self.assertEqual('published_import_failed',result.attrs['officials_report']['status'])

    def test_idempotent_even_when_forced(self):
        self.sync()
        before = officials.CACHE.read_bytes()
        self.sync()
        self.assertEqual(before,officials.CACHE.read_bytes())

    def test_partial_live_does_not_remove_cached_appointment(self):
        self.sync()
        before=officials.CACHE.read_bytes()
        self.remove_one()
        result=self.sync()
        self.assertEqual(10,len(result))
        self.assertEqual(before,officials.CACHE.read_bytes())
        self.assertEqual('published_import_failed',result.attrs['officials_report']['status'])

    def test_other_rounds_preserved(self):
        previous=pd.DataFrame([dict(match_round=4,home_team='Old',away_team='Other',
            referee='J Brooks',source='historical',synced_at='original')])
        previous.to_csv(officials.CACHE,index=False)
        self.sync()
        actual=pd.read_csv(officials.CACHE)
        pd.testing.assert_frame_equal(previous,actual[actual.match_round==4].reset_index(drop=True))

    def test_conflict_preserves_entire_cache(self):
        self.sync()
        before=officials.CACHE.read_bytes()
        self.html=self.html.replace('Paul Tierney.','John Brooks.',1)
        result=self.sync()
        self.assertEqual(before,officials.CACHE.read_bytes())
        self.assertEqual('published_import_failed',result.attrs['officials_report']['status'])

    def test_discovery_without_known_url(self):
        with patch.object(officials,'KNOWN_URLS',{}):
            self.assertEqual(EXPECTED,self.appointments(self.sync()))
        self.assertTrue(any(c.args[0]==officials.CONTENT_API for c in self.net.call_args_list))

    def test_unpublished_is_distinct_from_offline(self):
        with patch.object(officials,'KNOWN_URLS',{}):
            self.net.side_effect=None
            self.net.return_value=Mock(json=Mock(return_value={'content':[]}),raise_for_status=Mock())
            self.assertEqual('unpublished',self.sync().attrs['officials_report']['status'])
            self.net.side_effect=requests.ConnectionError('offline')
            self.assertEqual('discovery_failed',self.sync().attrs['officials_report']['status'])

    def test_discovery_ignores_previous_season_and_other_round(self):
        self.net.side_effect=None
        self.net.return_value=Mock(json=Mock(return_value={'content':[
            dict(id=1,title='Match officials for Matchweek 6',description='2025/26 fixtures'),
            dict(id=2,title='Match officials for Matchweek 60',description='2026/27 fixtures'),
        ]}),raise_for_status=Mock())
        self.assertIsNone(officials._discover_url(6))

    def test_cli_fails_for_published_incomplete(self):
        self.remove_one()
        self.assertEqual(1,officials.main(['--round','6']))

    def test_verified_fallback(self):
        known={6:[(h,a,ref) for (h,a),ref in EXPECTED.items()]}
        self.net.side_effect=requests.ConnectionError('offline')
        with patch.object(officials,'KNOWN_APPOINTMENTS',known):
            self.assertEqual(EXPECTED,self.appointments(self.sync()))

    def test_summary_lists_missing_fixture(self):
        self.remove_one()
        summary=self.base/'summary.md'
        with patch.dict(os.environ,{'GITHUB_STEP_SUMMARY':str(summary)}):
            self.assertEqual(1,officials.main(['--round','6']))
        text=summary.read_text(encoding='utf-8')
        self.assertIn('found: 9; missing: 1',text)
        self.assertIn('MISSING: Arsenal',text)

    def test_discovery_paginates(self):
        first=[dict(id=i,title='Other article',date='2026-10-01') for i in range(50)]
        last=[dict(id=4729629,title='Match officials for Matchweek 6',description='2026/27')]
        self.net.side_effect=[Mock(json=Mock(return_value={'content':rows}),raise_for_status=Mock())
                              for rows in (first,last)]
        self.assertIn('/4729629/',officials._discover_url(6))
        self.assertEqual(50,self.net.call_args.kwargs['params']['offset'])

    def test_broken_pagination_is_not_unpublished(self):
        rows=[dict(id=i,title='Other article',date='2026-10-01') for i in range(50)]
        self.net.side_effect=None
        self.net.return_value=Mock(json=Mock(return_value={'content':rows}),raise_for_status=Mock())
        with patch.object(officials,'KNOWN_URLS',{}):
            self.assertEqual('discovery_failed',self.sync().attrs['officials_report']['status'])

    def test_placeholder_is_not_a_valid_referee(self):
        self.html=self.html.replace('Paul Tierney.','Not appointed.',1)
        self.assertNotIn(('Arsenal','Leeds'),self.appointments(self.sync()))

    def test_failed_cache_publication_preserves_original_bytes(self):
        previous=pd.DataFrame([dict(match_round=4,home_team='Old',away_team='Other',
            referee='J Brooks',source='historical',synced_at='original')])
        previous.to_csv(officials.CACHE,index=False)
        before=officials.CACHE.read_bytes()
        with patch.object(officials.os,'replace',side_effect=OSError('publication failed')):
            with self.assertRaises(OSError):self.sync()
        self.assertEqual(before,officials.CACHE.read_bytes())
        self.assertEqual([],list(self.base.glob('*.tmp')))

    def test_complete_cache_skips_network(self):
        self.sync()
        self.net.reset_mock()
        officials.sync_officials(6)
        self.net.assert_not_called()


class OrchestrationTests(unittest.TestCase):
    def test_officials_failure_deferred_past_settlements_and_preservation_signal(self):
        with tempfile.TemporaryDirectory() as tmp:
            output=Path(tmp)/'output'
            calls=[]
            def run(args,required=True):
                calls.append(args[1])
                return 1 if args[1]=='scripts/update_officials.py' else 0
            with patch.object(auto_update,'run',side_effect=run), patch.object(auto_update,'validate_current_state'), patch.dict(os.environ,{'GITHUB_OUTPUT':str(output)}):
                with self.assertRaises(SystemExit) as exc:
                    auto_update.main()
            self.assertEqual(1,exc.exception.code)
            self.assertLess(calls.index('scripts/prediction_archive.py'),calls.index('scripts/update_officials.py'))
            self.assertLess(calls.index('scripts/model_prediction_stats.py'),calls.index('scripts/update_officials.py'))
            self.assertNotIn('scripts/snapshot_model_predictions.py',calls)
            self.assertEqual('data_completed=true\n',output.read_text())

    def test_critical_failure_does_not_signal_publishable_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            output=Path(tmp)/'output'
            with patch.object(auto_update,'run',side_effect=SystemExit(2)), patch.dict(os.environ,{'GITHUB_OUTPUT':str(output)}):
                with self.assertRaises(SystemExit):auto_update.main()
            self.assertFalse(output.exists())


if __name__ == '__main__':
    unittest.main()
