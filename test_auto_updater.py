import unittest
from datetime import date

from auto_updater import (
    extract_event_candidates,
    extract_primary_event,
    extract_section_events,
    library_campaign_short_name,
    normalize_known_event_name,
    remove_expired_events,
)


FETCHED_AT = "2026-08-17T10:00:00+09:00"
SOURCE_URL = "https://www.monster-strike.com/news/20260813_3.html"


class AutoUpdaterTest(unittest.TestCase):
    def test_campaign_article_is_split_into_individual_periods(self):
        sections = [
            (
                "英雄の神殿でわくわくの実が2個",
                "英雄の神殿でわくわくの実が2個 "
                "2026年8月17日（月）0:00～8月18日（火）23:59 "
                "2026年8月24日（月）0:00～8月25日（火）23:59",
            ),
            (
                "追憶の書庫で金卵の排出率2倍",
                "追憶の書庫で金卵の排出率2倍 "
                "2026年8月25日（火）0:00～8月29日（土）23:59 "
                "対象クエスト 8/25 闇属性クエスト 8/26 木属性クエスト "
                "8/27 光属性クエスト 8/28 水属性クエスト "
                "8/29 火属性クエスト",
            ),
        ]

        candidates = extract_section_events(sections, SOURCE_URL, FETCHED_AT)

        self.assertEqual(len(candidates), 3)
        self.assertEqual(candidates[0]["start_date"], "2026-08-17")
        self.assertEqual(candidates[1]["start_date"], "2026-08-24")
        self.assertEqual(candidates[0]["start_time"], "00:00")
        self.assertEqual(candidates[0]["end_time"], "23:59")
        self.assertEqual(candidates[2]["category"], "育成キャンペーン")
        self.assertEqual(candidates[0]["short_name"], "神殿CP・わくわく×2")
        self.assertEqual(
            candidates[2]["short_name"],
            "書庫卵2倍CP(闇・木・光・水・火)",
        )
        self.assertEqual(candidates[2]["daily_labels"], "闇・木・光・水・火")

        mission_sections = [
            (
                "期間限定「クエストサーチ活用ミッション」開催！",
                "対象期間 2026年8月19日（水）4:00～8月24日（月）3:59",
            ),
            (
                "期間限定「タイムシフト活用ミッション」開催！",
                "対象期間 2026年8月24日（月）4:00～8月29日（土）3:59",
            ),
        ]
        mission_candidates = extract_section_events(
            mission_sections, SOURCE_URL, FETCHED_AT
        )
        self.assertEqual(
            [candidate["short_name"] for candidate in mission_candidates],
            ["サーチミッション", "タイムシフトミッション"],
        )

    def test_collaboration_gacha_is_a_separate_candidate(self):
        sections = [
            (
                "ガチャ「ブルーロック」開催！",
                "ガチャ「ブルーロック」開催！ ガチャ開催期間 "
                "2026年8月16日（日）12:00～9月2日（水）11:59",
            )
        ]

        candidates = extract_section_events(sections, SOURCE_URL, FETCHED_AT)

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["name"], "ブルーロックガチャ")
        self.assertEqual(candidates[0]["category"], "ガチャ")
        self.assertEqual(candidates[0]["end_date"], "2026-09-02")

        article_candidates, expired_count = extract_event_candidates(
            title="【ブルーロック×モンスト】コラボイベントが8/16より開催！",
            text=(
                "コラボイベント開催期間 "
                "2026年8月16日（日）12:00～9月2日（水）11:59"
            ),
            sections=sections,
            source_url=SOURCE_URL,
            fetched_at=FETCHED_AT,
            reference_date=date(2026, 8, 17),
        )
        collaboration_gacha = next(
            candidate
            for candidate in article_candidates
            if candidate["name"] == "ブルーロックコラボガチャ"
        )
        self.assertEqual(expired_count, 0)
        self.assertEqual(collaboration_gacha["category"], "コラボガチャ")

    def test_body_keyword_does_not_change_an_unrelated_heading(self):
        sections = [
            (
                "コラボクエストが登場！",
                "コラボクエストが登場！ タイムシフトでも挑戦可能。"
                "出現期間 2026年8月16日（日）12:00～9月2日（水）11:59",
            )
        ]

        candidates = extract_section_events(sections, SOURCE_URL, FETCHED_AT)

        self.assertEqual(candidates, [])

    def test_primary_gacha_replaces_duplicate_section_gacha(self):
        title = "アゲインガチャをアゲイン？！アゲアゲガチャ開催！"
        text = (
            "ガチャ開催期間 "
            "2026年8月10日（月）12:00～8月20日（木）11:59"
        )
        sections = [
            (
                "アゲインガチャをアゲイン？！アゲアゲガチャ開催！",
                text,
            )
        ]

        candidates, expired_count = extract_event_candidates(
            title=title,
            text=text,
            sections=sections,
            source_url=SOURCE_URL,
            fetched_at=FETCHED_AT,
            reference_date=date(2026, 8, 17),
        )

        self.assertEqual(expired_count, 0)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["name"], "アゲインガチャ")
        self.assertEqual(candidates[0]["category"], "周年CP")

    def test_again_gacha_names_are_normalized_across_articles(self):
        long_name = normalize_known_event_name({
            "name": "アゲインガチャをアゲイン？！アゲアゲガチャ開催！",
            "short_name": "アゲインガチャをアゲイン",
        })
        short_name = normalize_known_event_name({
            "name": "アゲインガチャ",
            "short_name": "アゲインガチャ",
        })

        self.assertEqual(long_name["name"], "アゲインガチャ")
        self.assertEqual(long_name["short_name"], "アゲインガチャ")
        self.assertEqual(long_name["category"], "周年CP")
        self.assertEqual(long_name, short_name)

    def test_collaboration_missions_are_classified_by_content(self):
        sections = [
            (
                "「セレクションミッション」開催！",
                "開催期間 2026年8月16日（日）12:00～9月5日（土）3:59",
            ),
            (
                "期間限定ミッション登場！",
                "入手方法『その他』のキャラクターを2体以上入れて交代劇をクリア "
                "挑戦可能期間 2026年8月18日（火）19:00～9月5日（土）3:59",
            ),
            (
                "期間限定ミッション登場！",
                "アプリから特設サイトの本キャンペーンに参加 "
                "開催期間 2026年8月16日（日）4:00～9月2日（水）11:29",
            ),
        ]

        candidates, expired_count = extract_event_candidates(
            title="【ブルーロック×モンスト】コラボイベントが8/16より開催！",
            text=(
                "コラボイベント開催期間 "
                "2026年8月16日（日）12:00～9月2日（水）11:59"
            ),
            sections=sections,
            source_url=SOURCE_URL,
            fetched_at=FETCHED_AT,
            reference_date=date(2026, 8, 17),
        )

        mission_candidates = [
            candidate
            for candidate in candidates
            if candidate["category"] == "コラボミッション"
        ]
        self.assertEqual(expired_count, 0)
        self.assertEqual(
            [candidate["name"] for candidate in mission_candidates],
            ["コラボミッション", "その他クリアミッション"],
        )

    def test_multiplayer_stamina_campaign_has_clear_label(self):
        sections = [
            (
                "マルチプレイでホストのスタミナが回復！",
                "対象期間 2026年8月16日（日）0:00～8月22日（土）23:59",
            )
        ]

        candidate = extract_section_events(
            sections, SOURCE_URL, FETCHED_AT
        )[0]

        self.assertEqual(candidate["short_name"], "マルチ・スタミナバックCP")
        self.assertEqual(candidate["category"], "マルチキャンペーン")

    def test_library_attribute_order_uses_article_order(self):
        section_text = (
            "対象クエスト 9/1 火属性クエスト 9/2 光属性クエスト "
            "9/3 闇属性クエスト 9/4 水属性クエスト 9/5 木属性クエスト"
        )

        short_name = library_campaign_short_name(section_text)

        self.assertEqual(short_name, "書庫卵2倍CP(火・光・闇・水・木)")

    def test_gacha_period_has_priority_over_quest_period(self):
        title = "2種類の期間限定ガチャや『復刻』モンスト夏休みが開催！"
        text = (
            "ガチャ開催期間 2026年8月11日（火）12:00～8月13日（木）11:59 "
            "クエスト出現期間 2026年8月11日（火）12:00～8月15日（土）11:59"
        )

        candidate = extract_primary_event(
            title, text, SOURCE_URL, FETCHED_AT
        )

        self.assertEqual(candidate["name"], "モンスト夏休み2026 復刻ガチャ")
        self.assertEqual(candidate["end_date"], "2026-08-13")
        self.assertEqual(candidate["category"], "ガチャ")

    def test_unopened_cave_is_regular_content(self):
        title = "新たな期間限定イベント『未開の幻洞』が8/14より登場！"
        text = (
            "初出現期間 "
            "2026年8月14日（金）12:00～8月29日（土）11:59"
        )

        candidate = extract_primary_event(
            title, text, SOURCE_URL, FETCHED_AT
        )

        self.assertEqual(candidate["name"], "未開の幻洞")
        self.assertEqual(candidate["category"], "定期コンテンツ")

    def test_expired_events_are_removed(self):
        events = [
            {"name": "終了", "end_date": "2026-08-16"},
            {"name": "当日まで", "end_date": "2026-08-17"},
            {"name": "開催中", "end_date": "2026-08-20"},
        ]

        active, expired_count = remove_expired_events(
            events, reference_date=date(2026, 8, 17)
        )

        self.assertEqual([item["name"] for item in active], ["当日まで", "開催中"])
        self.assertEqual(expired_count, 1)

    def test_collaboration_name_is_shortened(self):
        title = "【ブルーロック×モンスト】コラボイベントが8/16より開催！"
        text = (
            "コラボイベント開催期間 "
            "2026年8月16日（日）12:00～9月2日（水）11:59"
        )

        candidate = extract_primary_event(
            title, text, SOURCE_URL, FETCHED_AT
        )

        self.assertEqual(candidate["name"], "ブルーロックコラボ")
        self.assertEqual(candidate["short_name"], "ブルーロックコラボ")
        self.assertEqual(candidate["end_date"], "2026-09-02")

    def test_evolution_label_contains_character_name(self):
        title = "「モネ」の獣神化・改が8/18より解禁！"
        text = "解禁日時 2026年8月18日（火）12:00"

        candidate = extract_primary_event(
            title, text, SOURCE_URL, FETCHED_AT
        )

        self.assertEqual(candidate["name"], "モネ")
        self.assertEqual(candidate["short_name"], "モネ、獣神化・改")


if __name__ == "__main__":
    unittest.main()
