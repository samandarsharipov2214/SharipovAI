import SwiftUI

struct DashboardView: View {
    @State private var snapshot = DashboardSnapshot.demo
    @State private var isLoading = false

    var body: some View {
        NavigationStack {
            ZStack {
                SATheme.background.ignoresSafeArea()
                ScrollView {
                    VStack(alignment: .leading, spacing: 18) {
                        header
                        heroCard
                        metrics
                        aiDecision
                    }
                    .padding(20)
                }
            }
            .navigationTitle("SharipovAI")
            .task { await refresh() }
            .refreshable { await refresh() }
        }
    }

    private var header: some View {
        HStack(spacing: 12) {
            ZStack {
                Circle().fill(SATheme.accent.gradient)
                Text("SA").font(.headline).bold()
            }
            .frame(width: 48, height: 48)

            VStack(alignment: .leading) {
                Text("SharipovAI OS").font(.title2).bold()
                Text("Единый dashboard для сайта, Telegram и iPhone")
                    .font(.caption)
                    .foregroundStyle(SATheme.textMuted)
            }
            Spacer()
        }
    }

    private var heroCard: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Капитал")
                .font(.caption)
                .foregroundStyle(SATheme.textMuted)
            Text(String(format: "%.2f USDT", snapshot.equity))
                .font(.system(size: 36, weight: .bold, design: .rounded))
            HStack {
                Text(String(format: "PnL %.2f", snapshot.pnl))
                    .foregroundStyle(snapshot.pnl >= 0 ? SATheme.positive : SATheme.negative)
                Spacer()
                Text(snapshot.riskLevel)
                    .font(.caption.bold())
                    .padding(.horizontal, 10)
                    .padding(.vertical, 6)
                    .background(SATheme.accent.opacity(0.22))
                    .clipShape(Capsule())
            }
        }
        .saPanel()
    }

    private var metrics: some View {
        HStack(spacing: 12) {
            MetricCard(title: "Решение", value: snapshot.decision, subtitle: "AI Engine")
            MetricCard(title: "Уверенность", value: String(format: "%.1f%%", snapshot.confidence), subtitle: "Consensus")
        }
    }

    private var aiDecision: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("AI объяснение")
                .font(.headline)
            Text("Приложение подключено к тому же backend, что сайт и Telegram Mini App. Когда обновится API, данные обновятся везде.")
                .font(.subheadline)
                .foregroundStyle(SATheme.textMuted)
        }
        .saPanel()
    }

    private func refresh() async {
        isLoading = true
        snapshot = await APIClient.shared.loadDashboard()
        isLoading = false
    }
}

struct MetricCard: View {
    let title: String
    let value: String
    let subtitle: String

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(title).font(.caption).foregroundStyle(SATheme.textMuted)
            Text(value).font(.headline).lineLimit(1).minimumScaleFactor(0.6)
            Text(subtitle).font(.caption2).foregroundStyle(SATheme.textMuted)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .saPanel()
    }
}

#Preview {
    DashboardView()
        .preferredColorScheme(.dark)
}
