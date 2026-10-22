import WidgetKit
import SwiftUI
import AppIntents
import LifeLogKit

// MARK: - Data

struct TodayWidgetEntry: TimelineEntry {
    struct Item: Identifiable {
        let id: String
        let title: String
        let icon: String
        let color: String
        let count: Int
        let oneTap: Bool
    }

    let date: Date
    let items: [Item]
    let morningDone: Bool
    let eveningDone: Bool
    let suggested: CheckInKind
    let studyText: String?

    static let sample = TodayWidgetEntry(
        date: Date(),
        items: [
            Item(id: "1", title: "Urge resisted", icon: "hand.tap.fill", color: "teal", count: 3, oneTap: true),
            Item(id: "2", title: "Gave in", icon: "hand.tap.fill", color: "teal", count: 1, oneTap: true),
            Item(id: "3", title: "Automatic pickup", icon: "iphone.gen3.radiowaves.left.and.right", color: "teal", count: 5, oneTap: true),
            Item(id: "4", title: "Coffee", icon: "cup.and.saucer.fill", color: "brown", count: 1, oneTap: true),
            Item(id: "5", title: "Scrolling episode", icon: "scroll.fill", color: "teal", count: 0, oneTap: false),
            Item(id: "6", title: "Medication", icon: "pills.fill", color: "mint", count: 0, oneTap: false),
        ],
        morningDone: true, eveningDone: false, suggested: .evening, studyText: "Day 4 of 42")

    static func load(date: Date = Date()) -> TodayWidgetEntry {
        let store = StoreFactory.shared
        let measures = store.measures()
        let settings = store.settings()
        let day = store.dayKey(for: date)
        let entries = store.entries(dayKey: day)
        let sessions = store.sessions(dayKey: day)
        let items = QuickLogger.favorites(from: measures).map { a in
            Item(id: a.id, title: a.title, icon: a.measure.icon, color: a.measure.color,
                 count: QuickLogger.count(of: a, in: entries), oneTap: a.isComplete && a.measure.cardinality == .multiple)
        }
        let morning = sessions.contains { $0.kind == .morning && $0.completedAt != nil }
        let evening = sessions.contains { $0.kind == .evening && $0.completedAt != nil }
        let hour = Calendar.current.component(.hour, from: date)
        let suggested: CheckInKind = (!morning && hour < settings.eveningStartsHour) ? .morning : .evening
        let study = settings.study(containing: day).map { "Day \($0.1) of \($0.0.lengthDays)" }
        return TodayWidgetEntry(date: date, items: items, morningDone: morning, eveningDone: evening,
                                suggested: suggested, studyText: study)
    }
}

struct TodayProvider: TimelineProvider {
    func placeholder(in context: Context) -> TodayWidgetEntry { .sample }

    func getSnapshot(in context: Context, completion: @escaping (TodayWidgetEntry) -> Void) {
        completion(context.isPreview ? .sample : .load())
    }

    func getTimeline(in context: Context, completion: @escaping (Timeline<TodayWidgetEntry>) -> Void) {
        let entry = TodayWidgetEntry.load()
        // Refresh hourly so counts reset after the day boundary and check-in suggestions change.
        let next = Calendar.current.date(byAdding: .hour, value: 1, to: entry.date) ?? entry.date.addingTimeInterval(3600)
        completion(Timeline(entries: [entry], policy: .after(next)))
    }
}

// MARK: - Quick log widget

struct QuickTileView: View {
    let item: TodayWidgetEntry.Item
    var compact = false

    var body: some View {
        let tint = Palette.color(item.color)
        VStack(alignment: .leading, spacing: compact ? 2 : 4) {
            HStack(alignment: .top) {
                Image(systemName: item.icon)
                    .font(.system(size: compact ? 13 : 15, weight: .semibold))
                    .foregroundStyle(tint)
                Spacer(minLength: 0)
                if item.count > 0 {
                    Text("\(item.count)")
                        .font(.caption2.weight(.bold).monospacedDigit())
                        .foregroundStyle(.secondary)
                }
            }
            Spacer(minLength: 0)
            HStack(spacing: 2) {
                Text(item.title)
                    .font(.system(size: compact ? 11 : 12, weight: .semibold))
                    .lineLimit(2)
                    .minimumScaleFactor(0.8)
                    .foregroundStyle(.primary)
                if !item.oneTap {
                    Image(systemName: "chevron.right").font(.system(size: 8, weight: .bold)).foregroundStyle(.tertiary)
                }
            }
        }
        .padding(compact ? 7 : 9)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .leading)
        .background(tint.opacity(0.16), in: RoundedRectangle(cornerRadius: 12, style: .continuous))
    }
}

struct QuickLogWidgetView: View {
    @Environment(\.widgetFamily) private var family
    let entry: TodayWidgetEntry

    private var capacity: Int {
        switch family {
        case .systemSmall: return 4
        case .systemMedium: return 6
        default: return 12
        }
    }

    private var columns: [GridItem] {
        Array(repeating: GridItem(.flexible(), spacing: 6), count: family == .systemSmall ? 2 : 3)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            if family == .systemLarge { header }
            if entry.items.isEmpty {
                Text("Star measures in LifeLog to add them here.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else {
                LazyVGrid(columns: columns, spacing: 6) {
                    ForEach(entry.items.prefix(capacity)) { item in
                        tile(item).frame(height: tileHeight)
                    }
                }
                Spacer(minLength: 0)
            }
        }
        .containerBackground(for: .widget) { Color(uiColor: .systemBackground) }
    }

    private var tileHeight: CGFloat {
        switch family {
        case .systemSmall: return 64
        case .systemMedium: return 64
        default: return 70
        }
    }

    @ViewBuilder
    private func tile(_ item: TodayWidgetEntry.Item) -> some View {
        if item.oneTap {
            Button(intent: QuickLogIntent(actionID: item.id)) {
                QuickTileView(item: item, compact: family == .systemSmall)
            }
            .buttonStyle(.plain)
        } else {
            Link(destination: URL(string: "lifelog://log/\(item.id)")!) {
                QuickTileView(item: item, compact: family == .systemSmall)
            }
        }
    }

    private var header: some View {
        HStack {
            Text("LifeLog").font(.headline)
            if let s = entry.studyText { Text(s).font(.caption).foregroundStyle(.secondary) }
            Spacer()
            Link(destination: URL(string: "lifelog://checkin/\(entry.suggested.rawValue)")!) {
                Label(entry.suggested == .morning ? (entry.morningDone ? "Morning ✓" : "Morning")
                                                  : (entry.eveningDone ? "Evening ✓" : "Evening"),
                      systemImage: entry.suggested.symbolName)
                    .font(.caption.weight(.semibold))
                    .padding(.horizontal, 8).padding(.vertical, 4)
                    .background(.tint.opacity(0.15), in: Capsule())
            }
        }
    }
}

struct QuickLogWidget: Widget {
    var body: some WidgetConfiguration {
        StaticConfiguration(kind: "LifeLogQuickLog", provider: TodayProvider()) { entry in
            QuickLogWidgetView(entry: entry)
        }
        .configurationDisplayName("Quick Log")
        .description("Log your starred items with one tap.")
        .supportedFamilies([.systemSmall, .systemMedium, .systemLarge])
    }
}

// MARK: - Check-in (Lock Screen)

struct CheckInWidgetView: View {
    @Environment(\.widgetFamily) private var family
    let entry: TodayWidgetEntry

    var body: some View {
        content
            .widgetURL(URL(string: "lifelog://checkin/\(entry.suggested.rawValue)"))
            .containerBackground(for: .widget) { Color.clear }
    }

    @ViewBuilder
    private var content: some View {
        switch family {
        case .accessoryCircular:
            ZStack {
                AccessoryWidgetBackground()
                VStack(spacing: 1) {
                    Image(systemName: entry.suggested.symbolName).font(.system(size: 16, weight: .semibold))
                    Text(done(entry.suggested) ? "Done" : "Check in").font(.system(size: 9, weight: .semibold))
                }
            }
        case .accessoryInline:
            Label(done(entry.suggested) ? "\(entry.suggested.shortTitle) check-in done" : "\(entry.suggested.shortTitle) check-in",
                  systemImage: entry.suggested.symbolName)
        default:
            VStack(alignment: .leading, spacing: 2) {
                Label("LifeLog", systemImage: "list.bullet.circle.fill").font(.headline).widgetAccentable()
                Text("Morning \(entry.morningDone ? "✓" : "–")  ·  Evening \(entry.eveningDone ? "✓" : "–")")
                    .font(.caption)
                if let s = entry.studyText { Text(s).font(.caption2).foregroundStyle(.secondary) }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    private func done(_ kind: CheckInKind) -> Bool { kind == .morning ? entry.morningDone : entry.eveningDone }
}

struct CheckInWidget: Widget {
    var body: some WidgetConfiguration {
        StaticConfiguration(kind: "LifeLogCheckIn", provider: TodayProvider()) { entry in
            CheckInWidgetView(entry: entry)
        }
        .configurationDisplayName("Check-in")
        .description("Shows today’s check-ins and opens the next one.")
        .supportedFamilies([.accessoryCircular, .accessoryRectangular, .accessoryInline])
    }
}

@main
struct LifeLogWidgetBundle: WidgetBundle {
    var body: some Widget {
        QuickLogWidget()
        CheckInWidget()
    }
}
