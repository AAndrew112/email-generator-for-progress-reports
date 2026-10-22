import XCTest
@testable import LifeLogKit

final class Clock {
    var date: Date
    init(_ iso: String) { date = ISO8601DateFormatter().date(from: iso)! }
    func advance(_ s: TimeInterval) { date = date.addingTimeInterval(s) }
}

func makeStore(_ device: String = "phone", clock: Clock, source: EntrySource = .iPhone) throws -> Store {
    let s = try Store.inMemory(deviceID: device, source: source)
    s.now = { clock.date }
    try s.seedIfNeeded()
    return s
}

let newYork = TimeZone(identifier: "America/New_York")!

final class StoreTests: XCTestCase {
    func testSeedIsIdempotentAndValid() throws {
        let clock = Clock("2026-10-19T12:00:00Z")
        let store = try makeStore(clock: clock)
        try store.seedIfNeeded()
        let measures = store.measures()
        XCTAssertEqual(measures.count, Seed.measures().count)
        var keys: [String: UUID] = [:]
        for m in measures {
            XCTAssertNil(keys[m.key], "duplicate key \(m.key)")
            keys[m.key] = m.id
        }
        for m in measures { XCTAssertEqual(m.validate(existingKeys: keys), [], m.key) }
        XCTAssertEqual(store.settings().studies.first?.startDay, "2026-10-19")
        XCTAssertEqual(store.settings().studies.first?.lengthDays, 42)
        // Every rating point is labelled.
        for m in measures { for f in m.fields where f.type == .rating {
            XCTAssertEqual(f.anchors.count, f.ratingRange.count, "\(m.key).\(f.key)")
        } }
    }

    func testSeedIDsAreStableAcrossDevices() {
        XCTAssertEqual(Seed.measures().map(\.id), Seed.measures().map(\.id))
        XCTAssertEqual(Seed.measures().first?.id.uuidString, "1F0E0000-0000-4000-8000-000000000001")
    }

    func testEntryRoundTripRevisionAndHistory() throws {
        let clock = Clock("2026-10-19T12:00:00Z")
        let store = try makeStore(clock: clock)
        let urge = store.measures().first { $0.key == "screen_urge" }!
        var e = store.makeEntry(for: urge, values: ["outcome": .choices(["resisted"]), "trigger": .choices([])])
        e = try store.saveEntry(e)
        XCTAssertEqual(e.revision, 1)
        XCTAssertNil(e.values["trigger"], "empty selections are not stored")
        XCTAssertEqual(store.entry(id: e.id)?.values["outcome"], .choices(["resisted"]))

        clock.advance(60)
        e.values["strength"] = .number(3)
        e.setOccurredAt(clock.date.addingTimeInterval(-3600))
        e = try store.saveEntry(e)
        XCTAssertEqual(e.revision, 2)
        XCTAssertEqual(store.entry(id: e.id)?.values["strength"], .number(3))

        try store.deleteEntry(id: e.id)
        XCTAssertTrue(store.entry(id: e.id)!.isDeleted)
        XCTAssertTrue(store.recentEntries().isEmpty)
        XCTAssertEqual(store.deletedEntries().count, 1)
        try store.restoreEntry(id: e.id)
        XCTAssertFalse(store.entry(id: e.id)!.isDeleted)

        let history = store.entryRevisions(entryID: e.id)
        XCTAssertEqual(history.map(\.changeKind), [.created, .updated, .deleted, .restored])
        XCTAssertEqual(history.map(\.revision), [1, 2, 3, 4])
        XCTAssertNil(history[0].snapshot.values["strength"])
    }

    func testZeroIsStoredAndMissingIsAbsent() throws {
        let clock = Clock("2026-10-19T22:00:00Z")
        let store = try makeStore(clock: clock)
        let anxiety = store.measures().first { $0.key == "anxiety" }!
        let e = try store.saveEntry(store.makeEntry(for: anxiety, values: ["rating": .number(0)]))
        XCTAssertEqual(store.entry(id: e.id)?.values["rating"], .number(0))
        let fog = store.measures().first { $0.key == "brain_fog" }!
        let e2 = try store.saveEntry(store.makeEntry(for: fog, values: [:]))
        XCTAssertNil(store.entry(id: e2.id)?.values["rating"])
    }

    func testDayBoundaryAndTimeZone() throws {
        // 01:30 New York on Oct 20 belongs to Oct 19 with a 4 AM boundary.
        let late = ISO8601DateFormatter().date(from: "2026-10-20T05:30:00Z")!
        XCTAssertEqual(DayKey.make(for: late, timeZone: newYork, boundaryHour: 4), "2026-10-19")
        XCTAssertEqual(DayKey.make(for: late, timeZone: newYork, boundaryHour: 0), "2026-10-20")
        XCTAssertEqual(DayKey.make(for: late, timeZone: TimeZone(identifier: "Europe/London")!, boundaryHour: 4), "2026-10-20")

        let clock = Clock("2026-10-20T05:30:00Z")
        let store = try makeStore(clock: clock)
        let pickup = store.measures().first { $0.key == "phone_pickup" }!
        var e = store.makeEntry(for: pickup)
        e.timeZoneID = newYork.identifier
        e = try store.saveEntry(e)
        XCTAssertEqual(e.dayKey, "2026-10-19")
        XCTAssertEqual(e.utcOffsetSeconds, -4 * 3600)

        var s = store.settings()
        s.dayBoundaryHour = 0
        try store.saveSettings(s)
        XCTAssertEqual(store.entry(id: e.id)?.dayKey, "2026-10-20")
        XCTAssertEqual(store.entry(id: e.id)?.revision, 1, "recomputing derived day keys is not an edit")
    }

    func testStudyDays() {
        let s = AppSettings.scrollingStudy
        XCTAssertEqual(s.dayNumber(for: "2026-10-19"), 1)
        XCTAssertEqual(s.dayNumber(for: "2026-11-29"), 42)
        XCTAssertNil(s.dayNumber(for: "2026-11-30"))
        XCTAssertNil(s.dayNumber(for: "2026-10-18"))
        XCTAssertEqual(s.endDay, "2026-11-29")
        XCTAssertEqual(DayKey.range("2026-10-30", "2026-11-02"), ["2026-10-30", "2026-10-31", "2026-11-01", "2026-11-02"])
        XCTAssertEqual(DayKey.weekday("2026-10-19"), "Mon")
    }

    func testMeasureKeysAndFieldsAreNeverLost() throws {
        let clock = Clock("2026-10-19T12:00:00Z")
        let store = try makeStore(clock: clock)
        var m = Measure(key: "", name: "Neck pain", group: "Custom", fields: [
            FieldDefinition(key: "level", label: "Level", type: .rating, minValue: 0, maxValue: 10,
                            anchors: [RatingAnchor(value: 0, label: "None"), RatingAnchor(value: 10, label: "Worst")]),
            FieldDefinition(key: "side", label: "Side", type: .choice, options: [ChoiceOption("Left"), ChoiceOption("Right")]),
        ])
        m = try store.saveMeasure(m)
        XCTAssertEqual(m.key, "neck_pain")
        XCTAssertEqual(m.revision, 1)

        // Same name → unique key.
        let dup = try store.saveMeasure(Measure(key: "", name: "Neck pain", group: "Custom", fields: m.fields.map {
            var f = $0; f.id = UUID(); return f
        }))
        XCTAssertEqual(dup.key, "neck_pain_2")

        clock.advance(10)
        var edited = m
        edited.key = "renamed"
        edited.name = "Neck & shoulder pain"
        edited.fields[0].key = "changed"
        edited.fields.remove(at: 1)
        edited = try store.saveMeasure(edited)
        XCTAssertEqual(edited.key, "neck_pain")
        XCTAssertEqual(edited.fields[0].key, "level")
        XCTAssertEqual(edited.fields.count, 2)
        XCTAssertTrue(edited.fields[1].isArchived)
        XCTAssertEqual(edited.revision, 2)

        // Saving without changes does not create a revision.
        let again = try store.saveMeasure(edited)
        XCTAssertEqual(again.revision, 2)
        XCTAssertEqual(store.measureRevisions(measureID: m.id).count, 2)

        // Option removal archives the option.
        var withOptions = store.measure(id: dup.id)!
        withOptions.fields[1].options.removeAll { $0.key == "left" }
        withOptions = try store.saveMeasure(withOptions)
        XCTAssertEqual(withOptions.fields[1].options.first { $0.key == "left" }?.isArchived, true)
    }

    func testValidation() {
        var m = Measure(key: "x", name: " ", group: "Custom", fields: [])
        XCTAssertTrue(m.validate().contains(.emptyName))
        XCTAssertTrue(m.validate().contains(.noFields))
        m.name = "X"
        m.fields = [FieldDefinition(key: "a", label: "A", type: .choice)]
        XCTAssertTrue(m.validate().contains(.missingOptions("A")))
        m.fields = [FieldDefinition(key: "a", label: "A", type: .rating, minValue: 5, maxValue: 5)]
        XCTAssertTrue(m.validate().contains(.invalidRatingRange("A")))
        XCTAssertEqual(m.validate(existingKeys: ["x": UUID()]).contains(.duplicateMeasureKey("x")), true)
    }

    func testSlug() {
        XCTAssertEqual(Slug.make("Brain fog!"), "brain_fog")
        XCTAssertEqual(Slug.make("  Café — crème  "), "cafe_creme")
        XCTAssertEqual(Slug.make("5 HTP"), "m_5_htp")
        XCTAssertEqual(Slug.unique("a", existing: ["a", "a_2"]), "a_3")
    }

    func testOneTapCapability() {
        let measures = Seed.measures()
        XCTAssertTrue(measures.first { $0.key == "phone_pickup" }!.canLogWithOneTap)
        XCTAssertFalse(measures.first { $0.key == "scroll_episode" }!.canLogWithOneTap)
        XCTAssertFalse(measures.first { $0.key == "screen_urge" }!.canLogWithOneTap)
    }

    func testFileBackedStorePersists() throws {
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: dir) }
        let url = dir.appendingPathComponent("db.sqlite")
        var id: UUID
        do {
            let store = try Store(url: url, deviceID: "a")
            try store.seedIfNeeded()
            let m = store.measures().first { $0.key == "phone_pickup" }!
            id = try store.saveEntry(store.makeEntry(for: m)).id
        }
        let reopened = try Store(url: url, deviceID: "a")
        try reopened.seedIfNeeded()
        XCTAssertNotNil(reopened.entry(id: id))
        XCTAssertEqual(reopened.measures().count, Seed.measures().count)
    }

    func testFormatting() {
        XCTAssertEqual(ValueText.duration(45 * 60), "45 min")
        XCTAssertEqual(ValueText.duration(80 * 60), "1 h 20 min")
        XCTAssertEqual(ValueText.duration(7200), "2 h")
        XCTAssertEqual(ValueText.number(3), "3")
        XCTAssertEqual(ValueText.number(2.5), "2.5")
        XCTAssertEqual(ValueText.shortDuration(90 * 60), "1.5h")
        let urge = Seed.measures().first { $0.key == "screen_urge" }!
        let e = Entry(measureID: urge.id, measureKey: urge.key, occurredAt: Date(),
                      values: ["outcome": .choices(["resisted"]), "strength": .number(3)])
        XCTAssertEqual(ValueText.summary(of: e, measure: urge), "Resisted · Strength: Strong")
    }

    func testSleepMath() {
        let f = ISO8601DateFormatter()
        func d(_ s: String) -> Date { f.date(from: s)! }
        let intervals: [SleepMath.Interval] = [
            .init(start: d("2026-10-19T03:00:00Z"), end: d("2026-10-19T11:00:00Z"), stage: .inBed),
            .init(start: d("2026-10-19T03:20:00Z"), end: d("2026-10-19T06:00:00Z"), stage: .asleep),
            .init(start: d("2026-10-19T05:00:00Z"), end: d("2026-10-19T07:00:00Z"), stage: .asleep), // overlap (other source)
            .init(start: d("2026-10-19T07:30:00Z"), end: d("2026-10-19T10:45:00Z"), stage: .asleep),
        ]
        let s = SleepMath.summarize(intervals)
        let expectedAsleep: TimeInterval = 13_200 + 11_700 // 03:20–07:00 plus 07:30–10:45
        XCTAssertEqual(s.bedtime, d("2026-10-19T03:00:00Z"))
        XCTAssertEqual(s.sleepOnset, d("2026-10-19T03:20:00Z"))
        XCTAssertEqual(s.wakeTime, d("2026-10-19T10:45:00Z"))
        XCTAssertEqual(s.asleepDuration, expectedAsleep)
        XCTAssertEqual(SleepMath.duration(onset: d("2026-10-19T03:20:00Z"), wake: d("2026-10-19T10:45:00Z")), 26_700)
        XCTAssertNil(SleepMath.duration(onset: d("2026-10-19T10:45:00Z"), wake: d("2026-10-19T03:20:00Z")))

        let ref = d("2026-10-19T12:00:00Z")
        let utc = TimeZone(identifier: "UTC")!
        XCTAssertEqual(SleepMath.lastNight(hour: 23, minute: 15, reference: ref, timeZone: utc), d("2026-10-18T23:15:00Z"))
        XCTAssertEqual(SleepMath.lastNight(hour: 6, minute: 50, reference: ref, timeZone: utc), d("2026-10-19T06:50:00Z"))
    }

    func testDecodingToleratesMissingKeys() throws {
        let json = #"{"id":"1F0E0000-0000-4000-8000-000000000099","key":"k","name":"N","fields":[{"id":"2F0E0000-0000-4000-8000-000000000001","key":"a","label":"A","type":"number"}]}"#
        let m = try JSONDecoder().decode(Measure.self, from: Data(json.utf8))
        XCTAssertEqual(m.group, "Custom")
        XCTAssertEqual(m.fields.first?.dailyAggregate, .automatic)
        XCTAssertTrue(m.isActive)
    }
}
