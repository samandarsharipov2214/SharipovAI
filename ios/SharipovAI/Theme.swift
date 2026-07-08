import SwiftUI

enum SATheme {
    static let background = Color(red: 0.03, green: 0.05, blue: 0.10)
    static let panel = Color(red: 0.06, green: 0.09, blue: 0.16)
    static let panelSoft = Color(red: 0.08, green: 0.12, blue: 0.21)
    static let accent = Color(red: 0.10, green: 0.45, blue: 1.00)
    static let accentSoft = Color(red: 0.16, green: 0.63, blue: 1.00)
    static let positive = Color(red: 0.18, green: 0.86, blue: 0.55)
    static let negative = Color(red: 1.00, green: 0.29, blue: 0.35)
    static let textMuted = Color.white.opacity(0.64)
}

struct SAPanel: ViewModifier {
    func body(content: Content) -> some View {
        content
            .padding(16)
            .background(
                RoundedRectangle(cornerRadius: 24, style: .continuous)
                    .fill(SATheme.panel)
                    .overlay(
                        RoundedRectangle(cornerRadius: 24, style: .continuous)
                            .stroke(Color.white.opacity(0.08), lineWidth: 1)
                    )
            )
    }
}

extension View {
    func saPanel() -> some View {
        modifier(SAPanel())
    }
}
