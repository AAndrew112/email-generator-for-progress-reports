import SwiftUI

/// Named colours a measure can use. Names are stored, so the palette can evolve.
enum Palette {
    static let names = ["blue", "indigo", "purple", "pink", "red", "orange", "yellow",
                        "green", "mint", "teal", "cyan", "brown", "gray"]

    static func color(_ name: String) -> Color {
        switch name {
        case "indigo": return .indigo
        case "purple": return .purple
        case "pink": return .pink
        case "red": return .red
        case "orange": return .orange
        case "yellow": return .yellow
        case "green": return .green
        case "mint": return .mint
        case "teal": return .teal
        case "cyan": return .cyan
        case "brown": return .brown
        case "gray": return .gray
        default: return .blue
        }
    }
}

/// Curated SF Symbols for the measure icon picker.
enum SymbolCatalog {
    static let symbols = [
        "circle.fill", "star.fill", "heart.fill", "bolt.fill", "flame.fill", "drop.fill", "leaf.fill",
        "sun.max.fill", "moon.fill", "moon.zzz.fill", "bed.double.fill", "cloud.fog.fill", "sparkles",
        "face.smiling", "brain.head.profile", "waveform.path.ecg", "lungs.fill", "allergens", "bandage.fill",
        "pills.fill", "cross.case.fill", "cup.and.saucer.fill", "mug.fill", "wineglass.fill", "fork.knife",
        "iphone.gen3", "iphone.gen3.radiowaves.left.and.right", "laptopcomputer", "tv.fill", "gamecontroller.fill",
        "scroll.fill", "hand.tap.fill", "hand.raised.fill", "scope", "target", "flag.checkered", "checkmark.seal.fill",
        "book.fill", "pencil", "briefcase.fill", "figure.walk", "figure.mind.and.body", "person.2.fill",
        "music.note", "hourglass", "timer", "clock.fill", "thermometer.medium", "eye.fill", "ear.fill",
        "arrow.uturn.backward.circle.fill", "exclamationmark.triangle.fill", "battery.25percent", "battery.100percent",
    ]
}

extension View {
    /// A tinted rounded-square icon used throughout the app.
    func iconBadge(color: Color, size: CGFloat = 32) -> some View {
        self
            .font(.system(size: size * 0.5, weight: .semibold))
            .foregroundStyle(.white)
            .frame(width: size, height: size)
            .background(color.gradient, in: RoundedRectangle(cornerRadius: size * 0.28, style: .continuous))
    }
}

struct MeasureIcon: View {
    let symbol: String
    let color: String
    var size: CGFloat = 32

    var body: some View {
        Image(systemName: symbol)
            .iconBadge(color: Palette.color(color), size: size)
            .accessibilityHidden(true)
    }
}
