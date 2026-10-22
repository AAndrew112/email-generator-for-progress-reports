import XCTest
@testable import LifeLogKit

final class SyncTests: XCTestCase {
    /// Simulates the WatchConnectivity round trip: encode → transfer → apply → receipt.
    func transfer(from a: Store, to b: Store) throws {
        let batch = a.pendingChanges()
        guard !batch.isEmpty else { return }
        let decoded = try SyncBatch.decode(try batch.encoded())
        try b.apply(decoded)
        try a.markSynced(batch.receipt)
    }

    func testWatchEntriesReachPhoneAndPendingClears() throws {
        let clock = Clock("2026-10-19T12:00:00Z")
        let phone = try makeStore("phone", clock: clock)
        let watch = try makeStore("watch", clock: clock, source: .watch)
        XCTAssertFalse(watch.hasPendingChanges, "seeds are not pending")

        let pickup = watch.measures().first { $0.key == "phone_pickup" }!
        let e = try watch.saveEntry(watch.makeEntry(for: pickup))
        XCTAssertEqual(e.source, .watch)
        XCTAssertTrue(watch.hasPendingChanges)

        try transfer(from: watch, to: phone)
        XCTAssertFalse(watch.hasPendingChanges)
        XCTAssertFalse(phone.hasPendingChanges, "applied records are not echoed")
        let onPhone = phone.entry(id: e.id)
        XCTAssertEqual(onPhone, e)
        XCTAssertEqual(phone.entryRevisions(entryID: e.id).last?.changeKind, .synced)

        // Re-applying the same batch is idempotent.
        let again = try phone.apply(SyncBatch(senderDeviceID: "watch", sentAt: clock.date, entries: [e]))
        XCTAssertEqual(again.ignored, 1)
        XCTAssertEqual(phone.allEntries().count, 1)
    }

    func testLastWriterWinsAndDeletionPropagates() throws {
        let clock = Clock("2026-10-19T12:00:00Z")
        let phone = try makeStore("phone", clock: clock)
        let watch = try makeStore("watch", clock: clock, source: .watch)
        let urge = phone.measures().first { $0.key == "screen_urge" }!
        let e = try phone.saveEntry(phone.makeEntry(for: urge, values: ["outcome": .choices(["resisted"])]))
        try transfer(from: phone, to: watch)

        // Both edit offline; the watch edits later.
        clock.advance(5)
        var p = phone.entry(id: e.id)!
        p.values["strength"] = .number(1)
        try phone.saveEntry(p)
        clock.advance(5)
        var w = watch.entry(id: e.id)!
        w.values["strength"] = .number(4)
        try watch.saveEntry(w)

        try transfer(from: phone, to: watch)
        try transfer(from: watch, to: phone)
        XCTAssertEqual(phone.entry(id: e.id)?.values["strength"], .number(4))
        XCTAssertEqual(watch.entry(id: e.id)?.values["strength"], .number(4))

        clock.advance(5)
        try watch.deleteEntry(id: e.id)
        try transfer(from: watch, to: phone)
        XCTAssertTrue(phone.entry(id: e.id)!.isDeleted)
        XCTAssertTrue(phone.recentEntries().isEmpty)
    }

    func testReceiptDoesNotClearNewerLocalEdit() throws {
        let clock = Clock("2026-10-19T12:00:00Z")
        let watch = try makeStore("watch", clock: clock, source: .watch)
        let pickup = watch.measures().first { $0.key == "phone_pickup" }!
        var e = try watch.saveEntry(watch.makeEntry(for: pickup))
        let sent = watch.pendingChanges()
        clock.advance(1)
        e.note = "edited after sending"
        try watch.saveEntry(e)
        try watch.markSynced(sent.receipt)
        XCTAssertTrue(watch.hasPendingChanges, "the newer edit must still be sent")
    }

    func testMeasureEditsAndSettingsSyncToWatch() throws {
        let clock = Clock("2026-10-19T12:00:00Z")
        let phone = try makeStore("phone", clock: clock)
        let watch = try makeStore("watch", clock: clock, source: .watch)
        clock.advance(60)
        var mood = phone.measures().first { $0.key == "mood" }!
        mood.name = "Mood today"
        mood.isFavorite = true
        try phone.saveMeasure(mood)
        let custom = try phone.saveMeasure(Measure(key: "", name: "Water", group: "Intake",
                                                   fields: [FieldDefinition(key: "glasses", label: "Glasses", type: .number)]))
        var s = phone.settings()
        s.dayBoundaryHour = 3
        try phone.saveSettings(s)

        try transfer(from: phone, to: watch)
        XCTAssertEqual(watch.measure(id: mood.id)?.name, "Mood today")
        XCTAssertEqual(watch.measure(id: custom.id)?.key, "water")
        XCTAssertEqual(watch.settings().dayBoundaryHour, 3)
        XCTAssertFalse(phone.hasPendingChanges)
    }

    func testChunking() {
        let m = Seed.measures()[0]
        let entries = (0..<350).map { _ in Entry(measureID: m.id, measureKey: m.key, occurredAt: Date()) }
        let batch = SyncBatch(senderDeviceID: "a", sentAt: Date(), measures: [m], entries: entries, settings: AppSettings())
        let chunks = batch.chunked(maxEntries: 150)
        XCTAssertEqual(chunks.map(\.entries.count), [150, 150, 50])
        XCTAssertEqual(chunks[0].measures.count, 1)
        XCTAssertNotNil(chunks[0].settings)
        XCTAssertTrue(chunks[1].measures.isEmpty)
    }

    func testConflictTieBreakIsDeterministic() {
        let t = Date()
        XCTAssertTrue(Conflict.remoteWins(local: (t, "a"), remote: (t, "b")))
        XCTAssertFalse(Conflict.remoteWins(local: (t, "b"), remote: (t, "a")))
        XCTAssertFalse(Conflict.remoteWins(local: (t, "a"), remote: (t, "a")))
        XCTAssertTrue(Conflict.remoteWins(local: (t, "z"), remote: (t.addingTimeInterval(1), "a")))
    }
}

final class ExportTests: XCTestCase {
    func parseCSV(_ text: String) -> [[String]] {
        var rows: [[String]] = []
        var row: [String] = []
        var field = ""
        var quoted = false
        var chars = Array(text)
        var i = 0
        while i < chars.count {
            let c = chars[i]
            if quoted {
                if c == "\"" {
                    if i + 1 < chars.count && chars[i + 1] == "\"" { field.append("\""); i += 1 } else { quoted = false }
                } else { field.append(c) }
            } else if c == "\"" { quoted = true }
            else if c == "," { row.append(field); field = "" }
            else if c == "\n" { row.append(field); rows.append(row); row = []; field = "" }
            else { field.append(c) }
            i += 1
        }
        chars.removeAll()
        return rows
    }

    func table(_ dir: URL, _ name: String) throws -> [[String: String]] {
        let rows = parseCSV(try String(contentsOf: dir.appendingPathComponent(name), encoding: .utf8))
        let header = rows[0]
        return rows.dropFirst().map { r in Dictionary(uniqueKeysWithValues: zip(header, r)) }
    }

    func testFullExport() throws {
        let clock = Clock("2026-10-19T11:00:00Z") // 07:00 New York
        let store = try makeStore(clock: clock)
        let ms = Dictionary(uniqueKeysWithValues: store.measures().map { ($0.key, $0) })
        let photos = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        let photoStore = PhotoStore(directory: photos)
        let photoName = try photoStore.save(jpeg: Data([0xFF, 0xD8, 0xFF]))
        defer { try? FileManager.default.removeItem(at: photos) }

        func log(_ key: String, _ values: [String: FieldValue], at iso: String, context: EntryContext = .quickLog, note: String? = nil) throws -> Entry {
            var e = store.makeEntry(for: ms[key]!, values: values, context: context, note: note)
            e.timeZoneID = newYork.identifier
            e.setOccurredAt(ISO8601DateFormatter().date(from: iso)!)
            return try store.saveEntry(e)
        }
        let f = ISO8601DateFormatter()
        // Day 1 (Oct 19): morning check-in, anxiety 0 in the evening, two scrolling episodes, a skin flare with photo.
        let session = try store.saveSession(CheckInSession(kind: .morning, dayKey: "", startedAt: clock.date,
                                                           completedAt: clock.date.addingTimeInterval(40), timeZone: newYork,
                                                           presentedMeasureKeys: ["sleep_times", "sleep_quality", "restedness"],
                                                           answeredMeasureKeys: ["sleep_times", "sleep_quality"],
                                                           skippedMeasureKeys: ["restedness"]))
        _ = try log("sleep_times", ["bedtime": .date(f.date(from: "2026-10-19T03:10:00Z")!),
                                    "sleep_onset": .date(f.date(from: "2026-10-19T03:30:00Z")!),
                                    "wake_time": .date(f.date(from: "2026-10-19T10:45:00Z")!),
                                    "sleep_duration": .duration(26_100)],
                    at: "2026-10-19T11:00:00Z", context: .morningCheckIn)
        _ = try log("sleep_quality", ["rating": .number(3)], at: "2026-10-19T11:00:10Z", context: .morningCheckIn)
        _ = try log("anxiety", ["rating": .number(0)], at: "2026-10-20T01:00:00Z", context: .eveningCheckIn,
                    note: "Calm, \"good\" day\nsecond line")
        _ = try log("scroll_episode", ["duration": .duration(900), "trigger": .choices(["bored", "avoiding_a_task"])],
                    at: "2026-10-19T15:00:00Z")
        _ = try log("scroll_episode", ["duration": .duration(1800)], at: "2026-10-20T04:30:00Z") // 00:30 local → Oct 19
        _ = try log("seb_derm", ["severity": .number(2), "locations": .choices(["scalp", "eyebrows"]),
                                 "photo": .photos([photoName])], at: "2026-10-19T16:00:00Z")
        // Day 2 (Oct 20): nothing. Day 3 (Oct 21): a pickup only.
        let deleted = try log("phone_pickup", [:], at: "2026-10-21T14:00:00Z")
        _ = try log("phone_pickup", [:], at: "2026-10-21T15:00:00Z")
        try store.deleteEntry(id: deleted.id)
        _ = session

        let out = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: out) }
        let result = try Exporter(store: store, photoDirectory: photos).export(to: out, options: ExportOptions(appVersion: "1.0"))
        XCTAssertEqual(result.photoCount, 1)
        XCTAssertEqual(result.entryCount, 7)
        for name in ["README.txt", "measures.csv", "entries.csv", "observations.csv", "daily.csv", "checkins.csv",
                     "edit_history.csv", "lifelog.json", "photos/\(photoName)"] {
            XCTAssertTrue(FileManager.default.fileExists(atPath: out.appendingPathComponent(name).path), name)
        }

        let entries = try table(out, "entries.csv")
        let anxiety = entries.first { $0["measure_key"] == "anxiety" }!
        XCTAssertEqual(anxiety["occurred_at"], "2026-10-19T21:00:00-04:00")
        XCTAssertEqual(anxiety["occurred_at_utc"], "2026-10-20T01:00:00Z")
        XCTAssertEqual(anxiety["day"], "2026-10-19")
        XCTAssertEqual(anxiety["study_day"], "1")
        XCTAssertEqual(anxiety["note"], "Calm, \"good\" day\nsecond line")
        XCTAssertEqual(anxiety["utc_offset_minutes"], "-240")
        let lateScroll = entries.first { $0["occurred_at_utc"] == "2026-10-20T04:30:00Z" }!
        XCTAssertEqual(lateScroll["local_date"], "2026-10-20")
        XCTAssertEqual(lateScroll["day"], "2026-10-19")
        XCTAssertEqual(lateScroll["ended_at"], "2026-10-20T01:00:00-04:00")

        let obs = try table(out, "observations.csv")
        let zero = obs.first { $0["measure_key"] == "anxiety" }!
        XCTAssertEqual(zero["value"], "0")
        XCTAssertEqual(zero["value_numeric"], "0")
        XCTAssertEqual(zero["value_label"], "Not at all")
        let triggers = obs.first { $0["field_key"] == "trigger" }!
        XCTAssertEqual(triggers["value"], "bored|avoiding_a_task")
        XCTAssertEqual(triggers["value_label"], "Bored|Avoiding a task")
        let onset = obs.first { $0["field_key"] == "sleep_onset" }!
        XCTAssertEqual(onset["value"], "2026-10-18T23:30:00-04:00")
        XCTAssertEqual(onset["value_numeric"], "23.5")
        XCTAssertEqual(obs.first { $0["field_key"] == "sleep_duration" }?["value"], "435")
        XCTAssertEqual(obs.first { $0["field_key"] == "photo" }?["value"], "photos/\(photoName)")
        XCTAssertFalse(obs.contains { $0["measure_key"] == "restedness" }, "skipped questions have no rows")

        let daily = try table(out, "daily.csv")
        XCTAssertEqual(daily.map { $0["day"]! }, ["2026-10-19", "2026-10-20", "2026-10-21"])
        let d1 = daily[0], d2 = daily[1], d3 = daily[2]
        XCTAssertEqual(d1["has_data"], "1")
        XCTAssertEqual(d1["anxiety"], "0")
        XCTAssertEqual(d1["brain_fog"], "", "unanswered is empty, not 0")
        XCTAssertEqual(d1["restedness"], "")
        XCTAssertEqual(d1["sleep_quality"], "3")
        XCTAssertEqual(d1["scroll_episode__n"], "2")
        XCTAssertEqual(d1["scroll_episode__duration__sum"], "45")
        XCTAssertEqual(d1["seb_derm__severity__max"], "2")
        XCTAssertEqual(d1["sleep_times__sleep_duration"], "435")
        XCTAssertEqual(d1["morning_checkin_at"], "2026-10-19T07:00:40-04:00")
        XCTAssertEqual(d2["has_data"], "0")
        XCTAssertEqual(d2["scroll_episode__n"], "", "no data at all → missing")
        XCTAssertEqual(d3["has_data"], "1")
        XCTAssertEqual(d3["scroll_episode__n"], "0", "day with data but no episodes → 0")
        XCTAssertEqual(d3["scroll_episode__duration__sum"], "0")
        XCTAssertEqual(d3["phone_pickup__n"], "1", "deleted entries are not counted")
        XCTAssertEqual(d3["study_day"], "3")

        let checkins = try table(out, "checkins.csv")
        XCTAssertEqual(checkins.first?["skipped"], "restedness")

        let measures = try table(out, "measures.csv")
        let anxDef = measures.first { $0["measure_key"] == "anxiety" }!
        XCTAssertEqual(anxDef["anchors"], "0=Not at all | 1=A little | 2=Moderately | 3=Quite a bit | 4=Extremely")

        let history = try table(out, "edit_history.csv")
        XCTAssertEqual(history.filter { $0["entry_id"] == deleted.id.uuidString }.map { $0["change_kind"]! }, ["created", "deleted"])

        // JSON round trip into a fresh store reproduces the data without duplicates.
        let json = try Data(contentsOf: out.appendingPathComponent("lifelog.json"))
        let restored = try Store.inMemory(deviceID: "new-phone")
        try restored.seedIfNeeded()
        let r1 = try BackupImporter.importJSON(json, into: restored)
        XCTAssertGreaterThan(r1.inserted, 0)
        XCTAssertEqual(restored.allEntries(includeDeleted: true).count, 8)
        XCTAssertEqual(restored.allEntries().count, 7)
        XCTAssertEqual(restored.entry(id: anxietyID(entries))?.values["rating"], .number(0))
        let r2 = try BackupImporter.importJSON(json, into: restored)
        XCTAssertEqual(r2.inserted, 0)
        XCTAssertEqual(restored.allEntries(includeDeleted: true).count, 8)
        XCTAssertThrowsError(try BackupImporter.importJSON(Data("{}".utf8), into: restored))
    }

    private func anxietyID(_ rows: [[String: String]]) -> UUID {
        UUID(uuidString: rows.first { $0["measure_key"] == "anxiety" }!["entry_id"]!)!
    }

    func testCSVEscaping() {
        XCTAssertEqual(CSVTable.escape("plain"), "plain")
        XCTAssertEqual(CSVTable.escape("a,b"), "\"a,b\"")
        XCTAssertEqual(CSVTable.escape("say \"hi\""), "\"say \"\"hi\"\"\"")
        XCTAssertEqual(CSVTable.escape("line\nbreak"), "\"line\nbreak\"")
    }
}
