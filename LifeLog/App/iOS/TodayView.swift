import SwiftUI
import LifeLogKit

struct TodayView: View {
    @Environment(AppModel.self) private var model
    @Environment(Router.self) private var router
    @State private var formAction: QuickAction?
    @State private var tapCount = 0

    private let columns = [GridItem(.adaptive(minimum: 104, maximum: 180), spacing: 10)]

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 22) {
                    header
                    HStack(spacing: 12) {
                        CheckInCard(kind: .morning)
                        CheckInCard(kind: .evening)
                    }

                    VStack(alignment: .leading, spacing: 10) {
                        SectionTitle("Quick log")
                        LazyVGrid(columns: columns, spacing: 10) {
                            ForEach(model.favorites) { action in
                                QuickTile(action: action, count: model.count(action)) { tap(action) }
                                    .contextMenu {
                                        Button { formAction = action } label: { Label("Log with details…", systemImage: "square.and.pencil") }
                                        Button { router.sheet = .pickMeasure } label: { Label("Log at an earlier time…", systemImage: "clock.arrow.circlepath") }
                                    }
                            }
                            MoreTile { router.sheet = .pickMeasure }
                        }
                        if model.favorites.isEmpty {
                            Text("Star measures or presets in the Measures tab to pin them here.")
                                .font(.footnote).foregroundStyle(.secondary)
                        }
                    }

                    VStack(alignment: .leading, spacing: 10) {
                        SectionTitle("Today")
                        VStack(spacing: 0) {
                            if model.todayEntries.isEmpty {
                                Text("Nothing logged yet today.")
                                    .foregroundStyle(.secondary)
                                    .frame(maxWidth: .infinity, alignment: .leading)
                                    .padding(14)
                            }
                            ForEach(Array(model.todayEntries.reversed().enumerated()), id: \.element.id) { i, entry in
                                if i > 0 { Divider().padding(.leading, 56) }
                                Button { router.sheet = .editEntry(entry.id) } label: {
                                    EntryRow(entry: entry, measure: model.measure(entry.measureID))
                                        .padding(.horizontal, 14)
                                        .padding(.vertical, 8)
                                        .contentShape(Rectangle())
                                }
                                .buttonStyle(.plain)
                                .contextMenu {
                                    Button { router.sheet = .editEntry(entry.id) } label: { Label("Edit", systemImage: "pencil") }
                                    Button(role: .destructive) { model.delete(entry.id) } label: { Label("Delete", systemImage: "trash") }
                                }
                            }
                        }
                        .background(Color(uiColor: .secondarySystemGroupedBackground),
                                    in: RoundedRectangle(cornerRadius: 16, style: .continuous))
                    }
                }
                .padding(.horizontal)
                .padding(.bottom, 90)
            }
            .background(Color(uiColor: .systemGroupedBackground))
            .sensoryFeedback(.impact(weight: .medium), trigger: tapCount)
            .navigationTitle("Today")
            .toolbar {
                ToolbarItem(placement: .primaryAction) {
                    Button { router.sheet = .pickMeasure } label: { Image(systemName: "plus.circle.fill").font(.title3) }
                        .accessibilityLabel("Log something")
                }
            }
            .sheet(item: $formAction) { action in
                EntryFormView(mode: .new(action, context: .quickLog, at: nil))
                    .environment(model)
            }
            .refreshable { model.reload() }
        }
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(Date().formatted(.dateTime.weekday(.wide).month(.wide).day()))
                .font(.subheadline.weight(.semibold))
                .foregroundStyle(.secondary)
            if let status = model.studyStatus {
                HStack(spacing: 6) {
                    Image(systemName: "flask.fill")
                    Text("\(status.0.name) · Day \(status.1) of \(status.0.lengthDays)")
                }
                .font(.caption.weight(.semibold))
                .foregroundStyle(.tint)
                .padding(.horizontal, 10)
                .padding(.vertical, 5)
                .background(.tint.opacity(0.12), in: Capsule())
            }
        }
    }

    private func tap(_ action: QuickAction) {
        tapCount += 1
        switch model.quickLog(action) {
        case .logged:
            break
        case .needsInput(let a, let existing):
            if let existing { router.sheet = .editEntry(existing.id) } else { router.sheet = .newEntry(actionID: a.id) }
        }
    }
}

struct SectionTitle: View {
    let title: String
    init(_ title: String) { self.title = title }
    var body: some View {
        Text(title).font(.title3.weight(.semibold))
    }
}

struct CheckInCard: View {
    let kind: CheckInKind
    @Environment(AppModel.self) private var model
    @Environment(Router.self) private var router

    var body: some View {
        let done = model.completedSession(kind)
        let count = model.checkInMeasures(kind).count
        let answered = model.checkInMeasures(kind).filter { model.todayEntry(for: $0) != nil }.count
        let tint: Color = kind == .morning ? .orange : .indigo
        Button { router.sheet = .checkIn(kind) } label: {
            VStack(alignment: .leading, spacing: 10) {
                HStack {
                    Image(systemName: kind.symbolName)
                        .font(.title3)
                        .foregroundStyle(tint)
                    Spacer()
                    if done != nil {
                        Image(systemName: "checkmark.circle.fill").foregroundStyle(.green)
                    }
                }
                VStack(alignment: .leading, spacing: 2) {
                    Text(kind.shortTitle).font(.headline).foregroundStyle(.primary)
                    Group {
                        if let done, let at = done.completedAt {
                            Text("Done \(at.formatted(date: .omitted, time: .shortened))")
                        } else if answered > 0 {
                            Text("\(answered) of \(count) answered")
                        } else {
                            Text("\(count) question\(count == 1 ? "" : "s")")
                        }
                    }
                    .font(.caption)
                    .foregroundStyle(.secondary)
                }
            }
            .padding(14)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(Color(uiColor: .secondarySystemGroupedBackground), in: RoundedRectangle(cornerRadius: 16, style: .continuous))
            .overlay {
                if done == nil && model.suggestedCheckIn == kind {
                    RoundedRectangle(cornerRadius: 16, style: .continuous).strokeBorder(tint.opacity(0.6), lineWidth: 1.5)
                }
            }
        }
        .buttonStyle(.plain)
        .accessibilityLabel("\(kind.title), \(done == nil ? "not done" : "done")")
        .accessibilityIdentifier("checkin-\(kind.rawValue)")
    }
}

struct QuickTile: View {
    let action: QuickAction
    let count: Int
    let onTap: () -> Void

    var body: some View {
        let tint = Palette.color(action.measure.color)
        Button(action: onTap) {
            VStack(alignment: .leading, spacing: 8) {
                HStack(alignment: .top) {
                    Image(systemName: action.measure.icon).iconBadge(color: tint, size: 30)
                    Spacer()
                    if count > 0 {
                        Text("\(count)")
                            .font(.caption.weight(.bold).monospacedDigit())
                            .foregroundStyle(tint)
                            .padding(.horizontal, 7).padding(.vertical, 2)
                            .background(tint.opacity(0.15), in: Capsule())
                    }
                }
                VStack(alignment: .leading, spacing: 1) {
                    Text(action.title)
                        .font(.subheadline.weight(.semibold))
                        .foregroundStyle(.primary)
                        .lineLimit(2)
                        .multilineTextAlignment(.leading)
                    if !action.isComplete {
                        Text("Tap to choose").font(.caption2).foregroundStyle(.secondary)
                    } else if let s = action.subtitle {
                        Text(s).font(.caption2).foregroundStyle(.secondary).lineLimit(1)
                    }
                }
                Spacer(minLength: 0)
            }
            .padding(12)
            .frame(maxWidth: .infinity, minHeight: 104, alignment: .topLeading)
            .background(Color(uiColor: .secondarySystemGroupedBackground), in: RoundedRectangle(cornerRadius: 16, style: .continuous))
        }
        .buttonStyle(PressableStyle())
        .accessibilityLabel("Log \(action.title)")
        .accessibilityIdentifier("tile-\(action.title)")
        .accessibilityValue(count > 0 ? "\(count) today" : "")
    }
}

struct MoreTile: View {
    let onTap: () -> Void
    var body: some View {
        Button(action: onTap) {
            VStack(spacing: 6) {
                Image(systemName: "ellipsis.circle").font(.title2)
                Text("More").font(.subheadline.weight(.semibold))
            }
            .foregroundStyle(.secondary)
            .frame(maxWidth: .infinity, minHeight: 104)
            .background(Color(uiColor: .secondarySystemGroupedBackground).opacity(0.6),
                        in: RoundedRectangle(cornerRadius: 16, style: .continuous))
        }
        .buttonStyle(PressableStyle())
    }
}

struct PressableStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .scaleEffect(configuration.isPressed ? 0.96 : 1)
            .animation(.snappy(duration: 0.15), value: configuration.isPressed)
    }
}

struct EntryRow: View {
    let entry: Entry
    let measure: Measure?
    var showDate = false

    var body: some View {
        HStack(spacing: 12) {
            MeasureIcon(symbol: measure?.icon ?? "circle", color: measure?.color ?? "gray", size: 30)
            VStack(alignment: .leading, spacing: 2) {
                HStack(spacing: 6) {
                    Text(measure?.name ?? entry.measureKey).font(.subheadline.weight(.semibold))
                    if entry.source == .watch { Image(systemName: "applewatch").font(.caption2).foregroundStyle(.secondary) }
                    if entry.revision > 1 { Image(systemName: "pencil").font(.caption2).foregroundStyle(.secondary) }
                }
                let summary = ValueText.summary(of: entry, measure: measure)
                if !summary.isEmpty {
                    Text(summary).font(.caption).foregroundStyle(.secondary).lineLimit(2)
                }
                if let note = entry.note {
                    Text(note).font(.caption).foregroundStyle(.tertiary).lineLimit(1)
                }
            }
            Spacer(minLength: 4)
            Text(showDate ? entry.occurredAt.formatted(date: .abbreviated, time: .shortened)
                          : entry.occurredAt.formatted(date: .omitted, time: .shortened))
                .font(.caption.monospacedDigit())
                .foregroundStyle(.secondary)
        }
        .padding(.vertical, 2)
        .accessibilityElement(children: .combine)
    }
}
