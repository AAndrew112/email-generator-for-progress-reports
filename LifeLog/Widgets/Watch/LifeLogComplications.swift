import WidgetKit
import SwiftUI

/// Complications are launchers: they open the Watch app straight into quick log
/// or the next check-in, so they never show stale data.
struct LauncherEntry: TimelineEntry {
    let date: Date
}

struct LauncherProvider: TimelineProvider {
    func placeholder(in context: Context) -> LauncherEntry { LauncherEntry(date: Date()) }
    func getSnapshot(in context: Context, completion: @escaping (LauncherEntry) -> Void) {
        completion(LauncherEntry(date: Date()))
    }
    func getTimeline(in context: Context, completion: @escaping (Timeline<LauncherEntry>) -> Void) {
        completion(Timeline(entries: [LauncherEntry(date: Date())], policy: .never))
    }
}

struct LauncherView: View {
    @Environment(\.widgetFamily) private var family
    let symbol: String
    let title: String
    let url: String

    var body: some View {
        content
            .widgetURL(URL(string: url))
            .containerBackground(for: .widget) { Color.clear }
    }

    @ViewBuilder
    private var content: some View {
        switch family {
        case .accessoryCircular:
            ZStack {
                AccessoryWidgetBackground()
                Image(systemName: symbol).font(.system(size: 20, weight: .semibold)).widgetAccentable()
            }
        case .accessoryCorner:
            Image(systemName: symbol).font(.system(size: 20, weight: .semibold)).widgetAccentable()
                .widgetLabel(title)
        case .accessoryInline:
            Label(title, systemImage: symbol)
        default:
            HStack(spacing: 8) {
                Image(systemName: symbol).font(.title3.weight(.semibold)).widgetAccentable()
                VStack(alignment: .leading) {
                    Text("LifeLog").font(.headline)
                    Text(title).font(.caption).foregroundStyle(.secondary)
                }
                Spacer(minLength: 0)
            }
        }
    }
}

struct QuickLogComplication: Widget {
    var body: some WidgetConfiguration {
        StaticConfiguration(kind: "LifeLogQuickLog", provider: LauncherProvider()) { _ in
            LauncherView(symbol: "plus", title: "Quick log", url: "lifelog://quicklog")
        }
        .configurationDisplayName("Quick Log")
        .description("Opens LifeLog’s quick log.")
        .supportedFamilies([.accessoryCircular, .accessoryCorner, .accessoryRectangular, .accessoryInline])
    }
}

struct CheckInComplication: Widget {
    var body: some WidgetConfiguration {
        StaticConfiguration(kind: "LifeLogCheckIn", provider: LauncherProvider()) { _ in
            LauncherView(symbol: "checklist", title: "Check in", url: "lifelog://checkin")
        }
        .configurationDisplayName("Check-in")
        .description("Opens the next LifeLog check-in.")
        .supportedFamilies([.accessoryCircular, .accessoryCorner, .accessoryRectangular, .accessoryInline])
    }
}

@main
struct LifeLogComplications: WidgetBundle {
    var body: some Widget {
        QuickLogComplication()
        CheckInComplication()
    }
}
