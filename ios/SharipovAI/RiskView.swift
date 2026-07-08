import SwiftUI

struct RiskView: View {
    @State private var riskPerTrade = 2.0
    @State private var maxDrawdown = 10.0
    @State private var minConfidence = 78.0

    var body: some View {
        NavigationStack {
            ZStack {
                SATheme.background.ignoresSafeArea()
                ScrollView {
                    VStack(alignment: .leading, spacing: 18) {
                        Text("Контроль риска")
                            .font(.largeTitle.bold())

                        RiskSlider(title: "Риск на сделку", value: $riskPerTrade, range: 0...10, suffix: "%")
                        RiskSlider(title: "Максимальная просадка", value: $maxDrawdown, range: 0...50, suffix: "%")
                        RiskSlider(title: "Минимальная уверенность", value: $minConfidence, range: 0...100, suffix: "%")

                        VStack(alignment: .leading, spacing: 10) {
                            Text("Статус защиты").font(.headline)
                            Text("Реальная торговля выключена. Сейчас работает безопасный Paper Trading.")
                                .foregroundStyle(SATheme.textMuted)
                        }
                        .saPanel()
                    }
                    .padding(20)
                }
            }
            .navigationTitle("Риск")
        }
    }
}

struct RiskSlider: View {
    let title: String
    @Binding var value: Double
    let range: ClosedRange<Double>
    let suffix: String

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Text(title).bold()
                Spacer()
                Text(String(format: "%.0f%@", value, suffix))
                    .foregroundStyle(SATheme.accentSoft)
            }
            Slider(value: $value, in: range)
                .tint(SATheme.accent)
        }
        .saPanel()
    }
}

#Preview {
    RiskView()
        .preferredColorScheme(.dark)
}
