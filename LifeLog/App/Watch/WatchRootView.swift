import SwiftUI
import WatchKit
import LifeLogKit

struct WatchRootView: View {
    @Environment(AppModel.self) private var model
    @Environment(WatchSync.self) private var sync
    @State private var entryAction: QuickAction?
    @State private var editEntry: Entry?
    @State private var checkIn: CheckInKind?

    var body: some View {
        NavigationStack {
            List {
                Section {
                    WatchCheckInRow(kind: model.suggestedCheckIn) { checkIn = $0 }
                }
                Section("Quick log") {
                    if model.favorites.isEmpty {
                        Text("Star items on your iPhone to show them here.").font(.footnote).foregroundStyle(.secondary)
                    }
                    ForEach(model.favorites) { action in
                        Button { tap(action) } label: { WatchActionRow(action: action, count: model.count(action)) }
                    }
                }
                Section {
                    NavigationLink {
                        WatchAllItemsView { tap($0) }
                    } label: {
                        Label("All items", systemImage: "square.grid.2x2")
                    }
                    NavigationLink {
                        WatchTodayView { editEntry = $0 }
                    } label: {
                        Label("Today · \(model.todayEntries.count)", systemImage: "list.bullet")
                    }
                    WatchCheckInRow(kind: model.suggestedCheckIn == .morning ? .evening : .morning, compact: true) { checkIn = $0 }
                }
                Section {
                    syncFooter
                }
            }
            .navigationTitle("LifeLog")
        }
        .overlay(alignment: .bottom) { WatchToast() }
        .sheet(item: $entryAction) { action in
            WatchEntryFlow(action: action).environment(model)
        }
        .sheet(item: $editEntry) { entry in
            NavigationStack { WatchEntryForm(entry: entry, isNew: false) }.environment(model)
        }
        .fullScreenCover(item: $checkIn) { kind in
            WatchCheckInView(kind: kind).environment(model)
        }
        .onOpenURL { url in
            if url.host == "checkin" { checkIn = model.suggestedCheckIn }
        }
    }

    private var syncFooter: some View {
        let pending = model.store.hasPendingChanges
        return HStack(spacing: 6) {
            Image(systemName: pending ? "arrow.triangle.2.circlepath" : "checkmark.circle")
                .foregroundStyle(pending ? .orange : .green)
            Text(pending ? "Will sync with iPhone" : "Up to date with iPhone")
        }
        .font(.footnote)
        .foregroundStyle(.secondary)
        .listRowBackground(Color.clear)
    }

    private func tap(_ action: QuickAction) {
        switch model.quickLog(action, context: .quickLog) {
        case .logged:
            WKInterfaceDevice.current().play(.success)
        case .needsInput(let a, let existing):
            if let existing { editEntry = existing } else { entryAction = a }
        }
    }
}

struct WatchActionRow: View {
    let action: QuickAction
    let count: Int

    var body: some View {
        HStack(spacing: 10) {
            MeasureIcon(symbol: action.measure.icon, color: action.measure.color, size: 28)
            VStack(alignment: .leading, spacing: 0) {
                Text(action.title).font(.headline).lineLimit(2)
                if !action.isComplete {
                    Text("Choose…").font(.caption2).foregroundStyle(.secondary)
                }
            }
            Spacer(minLength: 2)
            if count > 0 {
                Text("\(count)").font(.caption.monospacedDigit().weight(.semibold)).foregroundStyle(.secondary)
            }
        }
        .padding(.vertical, 2)
    }
}

struct WatchCheckInRow: View {
    @Environment(AppModel.self) private var model
    let kind: CheckInKind
    var compact = false
    let start: (CheckInKind) -> Void

    var body: some View {
        let done = model.completedSession(kind)
        Button { start(kind) } label: {
            HStack {
                Image(systemName: kind.symbolName).foregroundStyle(kind == .morning ? .orange : .indigo)
                VStack(alignment: .leading, spacing: 0) {
                    Text(compact ? kind.shortTitle : kind.title).font(compact ? .body : .headline)
                    if let at = done?.completedAt {
                        Text("Done \(at.formatted(date: .omitted, time: .shortened))").font(.caption2).foregroundStyle(.secondary)
                    } else if !compact {
                        Text("\(model.checkInMeasures(kind).count) questions").font(.caption2).foregroundStyle(.secondary)
                    }
                }
                Spacer()
                if done != nil { Image(systemName: "checkmark.circle.fill").foregroundStyle(.green) }
            }
        }
    }
}

struct WatchToast: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        if let toast = model.toast {
            HStack(spacing: 6) {
                Image(systemName: "checkmark.circle.fill").foregroundStyle(.green)
                Text(toast.title).font(.footnote.weight(.semibold)).lineLimit(1)
                Spacer(minLength: 2)
                Button("Undo") { model.undo(toast) }
                    .font(.footnote.weight(.semibold))
                    .buttonStyle(.borderless)
                    .foregroundStyle(.yellow)
            }
            .padding(.horizontal, 10)
            .padding(.vertical, 8)
            .background(.ultraThinMaterial, in: Capsule())
            .padding(.horizontal, 4)
            .transition(.move(edge: .bottom).combined(with: .opacity))
        }
    }
}

struct WatchAllItemsView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    let onPick: (QuickAction) -> Void

    var body: some View {
        let actions = model.quickActions
        List {
            ForEach(model.groups, id: \.self) { group in
                let items = actions.filter { $0.measure.group == group }
                if !items.isEmpty {
                    Section(group) {
                        ForEach(items) { a in
                            Button {
                                dismiss()
                                DispatchQueue.main.asyncAfter(deadline: .now() + 0.3) { onPick(a) }
                            } label: {
                                WatchActionRow(action: a, count: model.count(a))
                            }
                        }
                    }
                }
            }
        }
        .navigationTitle("All items")
    }
}

struct WatchTodayView: View {
    @Environment(AppModel.self) private var model
    let onEdit: (Entry) -> Void

    var body: some View {
        List {
            if model.todayEntries.isEmpty {
                Text("Nothing logged yet today.").foregroundStyle(.secondary)
            }
            ForEach(model.todayEntries.reversed()) { e in
                let m = model.measure(e.measureID)
                Button { onEdit(e) } label: {
                    VStack(alignment: .leading, spacing: 2) {
                        HStack {
                            Text(m?.name ?? e.measureKey).font(.headline).lineLimit(1)
                            Spacer()
                            Text(e.occurredAt.formatted(date: .omitted, time: .shortened))
                                .font(.caption2.monospacedDigit()).foregroundStyle(.secondary)
                        }
                        let summary = ValueText.summary(of: e, measure: m)
                        if !summary.isEmpty { Text(summary).font(.caption).foregroundStyle(.secondary).lineLimit(2) }
                    }
                }
                .swipeActions {
                    Button(role: .destructive) { model.delete(e.id) } label: { Label("Delete", systemImage: "trash") }
                }
            }
        }
        .navigationTitle("Today")
    }
}
