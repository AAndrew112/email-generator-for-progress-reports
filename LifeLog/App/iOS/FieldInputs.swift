import SwiftUI
import PhotosUI
import LifeLogKit

// MARK: - Layout helpers

/// Wraps children onto multiple lines, like tags.
struct FlowLayout: Layout {
    var spacing: CGFloat = 8

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let maxWidth = proposal.width ?? .infinity
        var x: CGFloat = 0, y: CGFloat = 0, row: CGFloat = 0, widest: CGFloat = 0
        for v in subviews {
            let s = v.sizeThatFits(.unspecified)
            if x > 0 && x + s.width > maxWidth {
                x = 0
                y += row + spacing
                row = 0
            }
            x += s.width + spacing
            row = max(row, s.height)
            widest = max(widest, x - spacing)
        }
        return CGSize(width: proposal.width ?? widest, height: y + row)
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        var x: CGFloat = 0, y: CGFloat = 0, row: CGFloat = 0
        for v in subviews {
            let s = v.sizeThatFits(.unspecified)
            if x > 0 && x + s.width > bounds.width {
                x = 0
                y += row + spacing
                row = 0
            }
            v.place(at: CGPoint(x: bounds.minX + x, y: bounds.minY + y), proposal: ProposedViewSize(s))
            x += s.width + spacing
            row = max(row, s.height)
        }
    }
}

struct Chip: View {
    let title: String
    var systemImage: String? = nil
    let isSelected: Bool
    var tint: Color = .accentColor
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            HStack(spacing: 4) {
                if let systemImage { Image(systemName: systemImage) }
                Text(title)
            }
            .font(.subheadline.weight(.medium))
            .padding(.horizontal, 12)
            .padding(.vertical, 8)
            .foregroundStyle(isSelected ? Color.white : Color.primary)
            .background(isSelected ? AnyShapeStyle(tint.gradient) : AnyShapeStyle(Color(uiColor: .tertiarySystemFill)),
                        in: Capsule())
            .contentShape(Capsule())
        }
        .buttonStyle(.plain)
        .accessibilityAddTraits(isSelected ? .isSelected : [])
    }
}

// MARK: - Field input

/// Edits one field's value. `nil` means "not answered" and is always reachable
/// (via Clear / tapping a selected option again), so missing never becomes zero.
struct FieldInput: View {
    enum Style { case form, large }

    let field: FieldDefinition
    var tint: Color = .accentColor
    @Binding var value: FieldValue?
    var style: Style = .form
    var suggestions: [String] = []
    /// Called after a discrete one-tap answer (rating, choice, yes/no, duration chip).
    var onAnswered: (() -> Void)? = nil

    var body: some View {
        switch field.type {
        case .rating: RatingInput(field: field, tint: tint, value: $value, style: style, onAnswered: onAnswered)
        case .number: NumberInput(field: field, tint: tint, value: $value)
        case .boolean: BooleanInput(tint: tint, value: $value, onAnswered: onAnswered)
        case .choice, .multiChoice: ChoiceInput(field: field, tint: tint, value: $value, onAnswered: onAnswered)
        case .time: TimeInput(value: $value)
        case .duration: DurationInput(field: field, tint: tint, value: $value, onAnswered: onAnswered)
        case .text: TextInput(field: field, tint: tint, value: $value, suggestions: suggestions)
        case .photo: PhotoInput(value: $value)
        }
    }
}

struct ClearButton: View {
    let action: () -> Void
    var body: some View {
        Button("Clear", role: .destructive, action: action)
            .font(.caption)
            .buttonStyle(.borderless)
    }
}

struct RatingInput: View {
    let field: FieldDefinition
    let tint: Color
    @Binding var value: FieldValue?
    var style: FieldInput.Style = .form
    var onAnswered: (() -> Void)?

    private var selected: Int? { value?.number.map { Int($0.rounded()) } }
    private var points: [Int] { Array(field.ratingRange) }

    var body: some View {
        if points.count > 7 {
            sliderBody
        } else if style == .large {
            VStack(spacing: 8) {
                ForEach(points, id: \.self) { p in
                    Button { choose(p) } label: {
                        HStack(spacing: 14) {
                            Text("\(p)")
                                .font(.title3.weight(.bold).monospacedDigit())
                                .frame(width: 28)
                            Text(field.anchorLabel(for: p) ?? "")
                                .font(.body.weight(.medium))
                            Spacer()
                            if selected == p { Image(systemName: "checkmark.circle.fill") }
                        }
                        .padding(.horizontal, 16)
                        .frame(minHeight: 52)
                        .foregroundStyle(selected == p ? Color.white : Color.primary)
                        .background(selected == p ? AnyShapeStyle(tint.gradient) : AnyShapeStyle(Color(uiColor: .secondarySystemGroupedBackground)),
                                    in: RoundedRectangle(cornerRadius: 14, style: .continuous))
                        .contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                    .accessibilityLabel("\(p), \(field.anchorLabel(for: p) ?? "")")
                }
            }
            .sensoryFeedback(.selection, trigger: selected)
        } else {
            VStack(alignment: .leading, spacing: 6) {
                HStack(spacing: 6) {
                    ForEach(points, id: \.self) { p in
                        Button { choose(p) } label: {
                            Text("\(p)")
                                .font(.headline.monospacedDigit())
                                .frame(maxWidth: .infinity, minHeight: 40)
                                .foregroundStyle(selected == p ? Color.white : Color.primary)
                                .background(selected == p ? AnyShapeStyle(tint.gradient) : AnyShapeStyle(Color(uiColor: .tertiarySystemFill)),
                                            in: RoundedRectangle(cornerRadius: 10, style: .continuous))
                        }
                        .buttonStyle(.plain)
                        .accessibilityLabel("\(p), \(field.anchorLabel(for: p) ?? "")")
                    }
                }
                HStack {
                    if let s = selected, let label = field.anchorLabel(for: s) {
                        Text(label).font(.caption.weight(.semibold)).foregroundStyle(tint)
                    } else {
                        Text(field.anchorLabel(for: points.first ?? 0) ?? "").font(.caption2).foregroundStyle(.secondary)
                        Spacer()
                        Text(field.anchorLabel(for: points.last ?? 0) ?? "").font(.caption2).foregroundStyle(.secondary)
                    }
                }
            }
            .sensoryFeedback(.selection, trigger: selected)
        }
    }

    private var sliderBody: some View {
        VStack(alignment: .leading, spacing: 6) {
            if let s = selected {
                HStack {
                    Text("\(s)").font(.title2.weight(.bold).monospacedDigit()).foregroundStyle(tint)
                    if let l = field.anchorLabel(for: s) { Text(l).font(.subheadline) }
                    Spacer()
                    ClearButton { value = nil }
                }
                Slider(value: Binding(get: { Double(s) }, set: { value = .number($0.rounded()) }),
                       in: Double(points.first ?? 0)...Double(points.last ?? 10), step: 1)
                    .tint(tint)
            } else {
                Button("Tap to rate") { value = .number(Double((points.first ?? 0) + (points.count / 2))) }
            }
            HStack {
                Text(field.anchorLabel(for: points.first ?? 0).map { "\(points.first ?? 0) = \($0)" } ?? "")
                Spacer()
                Text(field.anchorLabel(for: points.last ?? 0).map { "\(points.last ?? 0) = \($0)" } ?? "")
            }
            .font(.caption2)
            .foregroundStyle(.secondary)
        }
    }

    private func choose(_ p: Int) {
        if selected == p, style == .form {
            value = nil
        } else {
            value = .number(Double(p))
            onAnswered?()
        }
    }
}

struct NumberInput: View {
    let field: FieldDefinition
    let tint: Color
    @Binding var value: FieldValue?

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                TextField("Amount", value: Binding<Double?>(get: { value?.number }, set: { value = $0.map(FieldValue.number) }),
                          format: .number)
                    .keyboardType(.decimalPad)
                    .font(.title3.monospacedDigit())
                if let unit = field.unit, !unit.isEmpty { Text(unit).foregroundStyle(.secondary) }
                if value != nil { ClearButton { value = nil } }
            }
            if !field.quickValues.isEmpty {
                FlowLayout(spacing: 6) {
                    ForEach(field.quickValues, id: \.self) { q in
                        Chip(title: ValueText.number(q) + (field.unit.map { " \($0)" } ?? ""),
                             isSelected: value?.number == q, tint: tint) { value = .number(q) }
                    }
                }
            }
        }
    }
}

struct BooleanInput: View {
    let tint: Color
    @Binding var value: FieldValue?
    var onAnswered: (() -> Void)?

    var body: some View {
        HStack(spacing: 10) {
            option("Yes", true)
            option("No", false)
        }
    }

    private func option(_ title: String, _ b: Bool) -> some View {
        let selected = value?.bool == b
        return Button {
            if selected { value = nil } else { value = .bool(b); onAnswered?() }
        } label: {
            Text(title)
                .font(.headline)
                .frame(maxWidth: .infinity, minHeight: 44)
                .foregroundStyle(selected ? Color.white : Color.primary)
                .background(selected ? AnyShapeStyle(tint.gradient) : AnyShapeStyle(Color(uiColor: .tertiarySystemFill)),
                            in: RoundedRectangle(cornerRadius: 12, style: .continuous))
        }
        .buttonStyle(.plain)
    }
}

struct ChoiceInput: View {
    let field: FieldDefinition
    let tint: Color
    @Binding var value: FieldValue?
    var onAnswered: (() -> Void)?

    private var selected: [String] { value?.choiceKeys ?? [] }

    private var visibleOptions: [ChoiceOption] {
        field.options.filter { !$0.isArchived || selected.contains($0.key) }
    }

    var body: some View {
        FlowLayout(spacing: 8) {
            ForEach(visibleOptions) { option in
                Chip(title: option.label, isSelected: selected.contains(option.key), tint: tint) { toggle(option.key) }
            }
        }
        .sensoryFeedback(.selection, trigger: selected)
    }

    private func toggle(_ key: String) {
        if field.type == .choice {
            if selected == [key] { value = nil } else { value = .choices([key]); onAnswered?() }
        } else {
            var keys = selected
            if let i = keys.firstIndex(of: key) { keys.remove(at: i) } else { keys.append(key) }
            value = keys.isEmpty ? nil : .choices(keys)
        }
    }
}

struct TimeInput: View {
    @Binding var value: FieldValue?

    var body: some View {
        if let date = value?.date {
            HStack {
                DatePicker("", selection: Binding(get: { date }, set: { value = .date($0) }),
                           displayedComponents: [.date, .hourAndMinute])
                    .labelsHidden()
                Spacer()
                ClearButton { value = nil }
            }
        } else {
            Button {
                value = .date(Date())
            } label: {
                Label("Set time", systemImage: "clock")
            }
        }
    }
}

struct DurationInput: View {
    let field: FieldDefinition
    let tint: Color
    @Binding var value: FieldValue?
    var onAnswered: (() -> Void)?

    private var minutes: Int? { value?.duration.map { Int(($0 / 60).rounded()) } }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            let quick = field.quickValues.isEmpty ? [5, 10, 15, 30, 45, 60, 90, 120].map { Double($0 * 60) } : field.quickValues
            FlowLayout(spacing: 6) {
                ForEach(quick, id: \.self) { q in
                    Chip(title: ValueText.shortDuration(q), isSelected: value?.duration == q, tint: tint) {
                        if value?.duration == q { value = nil } else { value = .duration(q); onAnswered?() }
                    }
                }
            }
            HStack {
                Text(minutes.map { ValueText.duration(Double($0 * 60)) } ?? "Custom")
                    .font(.subheadline.monospacedDigit())
                    .foregroundStyle(minutes == nil ? .secondary : .primary)
                Spacer()
                Stepper("Minutes", value: Binding(get: { minutes ?? 0 }, set: { value = .duration(Double(max(0, $0) * 60)) }),
                        in: 0...(24 * 60), step: 5)
                    .labelsHidden()
                if value != nil { ClearButton { value = nil } }
            }
        }
        .sensoryFeedback(.selection, trigger: minutes)
    }
}

struct TextInput: View {
    let field: FieldDefinition
    let tint: Color
    @Binding var value: FieldValue?
    var suggestions: [String] = []

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            TextField(field.label, text: Binding(get: { value?.text ?? "" }, set: { value = $0.isEmpty ? nil : .text($0) }),
                      axis: .vertical)
                .lineLimit(1...5)
            if !suggestions.isEmpty {
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(spacing: 6) {
                        ForEach(suggestions, id: \.self) { s in
                            Chip(title: s, isSelected: value?.text == s, tint: tint) { value = .text(s) }
                        }
                    }
                }
            }
        }
    }
}

// MARK: - Photos

enum ImageProcessing {
    /// Re-encodes as JPEG at most `maxDimension` px. Re-encoding drops EXIF/GPS metadata.
    static func jpeg(from image: UIImage, maxDimension: CGFloat = 2048, quality: CGFloat = 0.82) -> Data? {
        let size = image.size
        let scale = min(1, maxDimension / max(size.width, size.height))
        let target = CGSize(width: (size.width * scale).rounded(), height: (size.height * scale).rounded())
        let format = UIGraphicsImageRendererFormat()
        format.scale = 1
        let resized = UIGraphicsImageRenderer(size: target, format: format).image { _ in
            image.draw(in: CGRect(origin: .zero, size: target))
        }
        return resized.jpegData(compressionQuality: quality)
    }
}

struct PhotoInput: View {
    @Binding var value: FieldValue?
    @State private var pickerItems: [PhotosPickerItem] = []
    @State private var showCamera = false
    @State private var error: String?

    private var names: [String] { value?.photoNames ?? [] }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            if !names.isEmpty {
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(spacing: 8) {
                        ForEach(names, id: \.self) { name in
                            PhotoThumbnail(name: name)
                                .overlay(alignment: .topTrailing) {
                                    Button { remove(name) } label: {
                                        Image(systemName: "xmark.circle.fill")
                                            .symbolRenderingMode(.palette)
                                            .foregroundStyle(.white, .black.opacity(0.6))
                                    }
                                    .padding(4)
                                    .accessibilityLabel("Remove photo")
                                }
                        }
                    }
                }
            }
            HStack(spacing: 16) {
                if UIImagePickerController.isSourceTypeAvailable(.camera) {
                    Button { showCamera = true } label: { Label("Camera", systemImage: "camera") }
                }
                PhotosPicker(selection: $pickerItems, maxSelectionCount: 4, matching: .images) {
                    Label("Library", systemImage: "photo.on.rectangle")
                }
            }
            .buttonStyle(.borderless)
            if let error { Text(error).font(.caption).foregroundStyle(.red) }
            Text("Photos are stored privately on this device and included in exports.")
                .font(.caption2).foregroundStyle(.secondary)
        }
        .onChange(of: pickerItems) { _, items in
            guard !items.isEmpty else { return }
            Task { await load(items) }
        }
        .fullScreenCover(isPresented: $showCamera) {
            CameraPicker { image in
                if let image { add(image) }
                showCamera = false
            }
            .ignoresSafeArea()
        }
    }

    private func load(_ items: [PhotosPickerItem]) async {
        for item in items {
            if let data = try? await item.loadTransferable(type: Data.self), let image = UIImage(data: data) {
                add(image)
            } else {
                error = "Couldn’t load a photo."
            }
        }
        pickerItems = []
    }

    private func add(_ image: UIImage) {
        guard let data = ImageProcessing.jpeg(from: image), let name = try? StoreFactory.photos.save(jpeg: data) else {
            error = "Couldn’t save the photo."
            return
        }
        value = .photos(names + [name])
    }

    private func remove(_ name: String) {
        let rest = names.filter { $0 != name }
        value = rest.isEmpty ? nil : .photos(rest)
        // The file itself is kept so earlier revisions of the entry still resolve.
    }
}

struct PhotoThumbnail: View {
    let name: String
    var size: CGFloat = 84

    var body: some View {
        Group {
            if let image = UIImage(contentsOfFile: StoreFactory.photos.url(for: name).path) {
                Image(uiImage: image).resizable().scaledToFill()
            } else {
                Image(systemName: "photo").foregroundStyle(.secondary)
            }
        }
        .frame(width: size, height: size)
        .background(Color(uiColor: .tertiarySystemFill))
        .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
    }
}

struct CameraPicker: UIViewControllerRepresentable {
    let completion: (UIImage?) -> Void

    func makeUIViewController(context: Context) -> UIImagePickerController {
        let picker = UIImagePickerController()
        picker.sourceType = .camera
        picker.delegate = context.coordinator
        return picker
    }

    func updateUIViewController(_ controller: UIImagePickerController, context: Context) {}

    func makeCoordinator() -> Coordinator { Coordinator(completion: completion) }

    final class Coordinator: NSObject, UIImagePickerControllerDelegate, UINavigationControllerDelegate {
        let completion: (UIImage?) -> Void
        init(completion: @escaping (UIImage?) -> Void) { self.completion = completion }

        func imagePickerController(_ picker: UIImagePickerController,
                                   didFinishPickingMediaWithInfo info: [UIImagePickerController.InfoKey: Any]) {
            completion(info[.originalImage] as? UIImage)
        }

        func imagePickerControllerDidCancel(_ picker: UIImagePickerController) { completion(nil) }
    }
}
