from db_timetables_mcp.client import parse_events, parse_stations

PLAN = """<timetable station="Dresden Hbf">
<s id="1-2611072300-5"><tl f="F" t="p" o="80" c="ICE" n="1606"/>
  <dp pt="2611072310" pp="12" ppth="Dresden-Neustadt|Leipzig Hbf|Berlin Hbf"/></s>
<s id="2-2611072300-7"><tl f="N" t="p" o="800" c="S" n="31234"/>
  <ar pt="2611072305" pp="1" l="1" ppth="Meißen|Radebeul Ost"/>
  <dp pt="2611072307" pp="1" l="1" ppth="Pirna|Bad Schandau"/></s>
</timetable>"""

CHANGES = """<timetable station="Dresden Hbf">
<s id="1-2611072300-5"><m id="r1" t="h" txt="Reparatur am Zug"/>
  <dp ct="2611072327" cp="10"/></s>
<s id="2-2611072300-7"><dp cs="c"/></s>
</timetable>"""


def test_departures_merge_delay_platform_and_cancellation():
    events = parse_events(PLAN, CHANGES, "departure")
    ice, s1 = events[1], events[0]
    assert s1.train == "S 1" and s1.cancelled
    assert ice.train == "ICE 1606"
    assert ice.delay_minutes == 17
    d = ice.to_dict("departure")
    assert d["to"] == "Berlin Hbf" and d["platform"] == "10" and d["platform_changed"]
    assert d["messages"] == ["Reparatur am Zug"]


def test_arrivals_use_origin():
    events = parse_events(PLAN, None, "arrival")
    assert len(events) == 1
    assert events[0].to_dict("arrival")["from"] == "Meißen"


def test_parse_stations():
    xml = '<stations><station name="Dresden Hbf" eva="8010085" ds100="DH"/></stations>'
    assert parse_stations(xml)[0].eva == "8010085"
