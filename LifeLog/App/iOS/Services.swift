import Foundation
import HealthKit
import UserNotifications
import LifeLogKit

/// Reads last night's sleep from Apple Health (read-only, optional).
final class HealthSleep: @unchecked Sendable {
    static let shared = HealthSleep()
    private let store = HKHealthStore()
    private let sleepType = HKCategoryType(.sleepAnalysis)

    var isAvailable: Bool { HKHealthStore.isHealthDataAvailable() }

    func requestAuthorization() async -> Bool {
        guard isAvailable else { return false }
        do {
            try await store.requestAuthorization(toShare: [], read: [sleepType])
            return true
        } catch {
            return false
        }
    }

    /// Sleep between 6 PM yesterday and 2 PM today (or now, if earlier).
    func lastNight(reference: Date = Date()) async -> SleepMath.Summary? {
        guard isAvailable else { return nil }
        let cal = Calendar.current
        let today = cal.startOfDay(for: reference)
        guard let start = cal.date(byAdding: .hour, value: -6, to: today),
              let latest = cal.date(byAdding: .hour, value: 14, to: today) else { return nil }
        let end = min(reference, latest)
        let predicate = HKQuery.predicateForSamples(withStart: start, end: end, options: [])
        let samples: [HKCategorySample] = await withCheckedContinuation { cont in
            let query = HKSampleQuery(sampleType: sleepType, predicate: predicate, limit: HKObjectQueryNoLimit,
                                      sortDescriptors: [NSSortDescriptor(key: HKSampleSortIdentifierStartDate, ascending: true)]) { _, results, _ in
                cont.resume(returning: (results as? [HKCategorySample]) ?? [])
            }
            store.execute(query)
        }
        let intervals: [SleepMath.Interval] = samples.compactMap { s in
            // 0 in bed, 2 awake; 1/3/4/5 are asleep (unspecified, core, deep, REM).
            let stage: SleepMath.Stage
            switch s.value {
            case 0: stage = .inBed
            case 2: stage = .awake
            case 1, 3, 4, 5: stage = .asleep
            default: return nil
            }
            return SleepMath.Interval(start: s.startDate, end: s.endDate, stage: stage)
        }
        let summary = SleepMath.summarize(intervals)
        return (summary.sleepOnset == nil && summary.bedtime == nil) ? nil : summary
    }
}

/// Local check-in reminders (no server involved).
enum Reminders {
    static let ids = ["lifelog.morning", "lifelog.evening"]

    @discardableResult
    static func apply(_ settings: AppSettings) async -> Bool {
        let center = UNUserNotificationCenter.current()
        center.removePendingNotificationRequests(withIdentifiers: ids)
        let wanted: [(CheckInKind, ReminderTime)] = [(.morning, settings.morningReminder), (.evening, settings.eveningReminder)]
            .filter { $0.1.isEnabled }
        guard !wanted.isEmpty else { return true }
        let granted = (try? await center.requestAuthorization(options: [.alert, .sound])) ?? false
        guard granted else { return false }
        for (kind, time) in wanted {
            let content = UNMutableNotificationContent()
            content.title = kind.title
            content.body = kind == .morning ? "How did you sleep? Takes under a minute." : "A quick look back at today."
            content.sound = .default
            content.userInfo = ["checkin": kind.rawValue]
            let trigger = UNCalendarNotificationTrigger(dateMatching: DateComponents(hour: time.hour, minute: time.minute),
                                                        repeats: true)
            try? await center.add(UNNotificationRequest(identifier: "lifelog.\(kind.rawValue)", content: content, trigger: trigger))
        }
        return true
    }
}

/// Builds a zipped export folder ready to share.
enum ExportService {
    static func makeExport(store: Store) throws -> (URL, ExportResult) {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.dateFormat = "yyyy-MM-dd-HHmm"
        let stamp = formatter.string(from: Date())
        let base = FileManager.default.temporaryDirectory.appendingPathComponent("LifeLogExports", isDirectory: true)
        try? FileManager.default.removeItem(at: base)
        let dir = base.appendingPathComponent("LifeLog-export-\(stamp)", isDirectory: true)
        let version = Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? ""
        let result = try Exporter(store: store, photoDirectory: StoreFactory.photosURL)
            .export(to: dir, options: ExportOptions(appVersion: version))
        return (try zip(dir), result)
    }

    /// Zips a directory using the system (NSFileCoordinator's `.forUploading`).
    static func zip(_ dir: URL) throws -> URL {
        var coordinationError: NSError?
        var copyError: Error?
        var output: URL?
        NSFileCoordinator().coordinate(readingItemAt: dir, options: [.forUploading], error: &coordinationError) { zipped in
            let dest = dir.deletingLastPathComponent().appendingPathComponent(dir.lastPathComponent + ".zip")
            do {
                try? FileManager.default.removeItem(at: dest)
                try FileManager.default.copyItem(at: zipped, to: dest)
                output = dest
            } catch {
                copyError = error
            }
        }
        if let e = coordinationError ?? copyError { throw e }
        guard let output else { throw CocoaError(.fileWriteUnknown) }
        return output
    }
}
