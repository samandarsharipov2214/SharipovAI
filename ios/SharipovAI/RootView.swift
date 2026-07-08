import SwiftUI

struct RootView: View {
    var body: some View {
        TabView {
            DashboardView()
                .tabItem { Label("Обзор", systemImage: "chart.line.uptrend.xyaxis") }

            AIChatView()
                .tabItem { Label("AI", systemImage: "sparkles") }

            PortfolioView()
                .tabItem { Label("Портфель", systemImage: "briefcase.fill") }

            TradesView()
                .tabItem { Label("Сделки", systemImage: "list.bullet.rectangle") }

            RiskView()
                .tabItem { Label("Риск", systemImage: "shield.fill") }
        }
        .tint(SATheme.accent)
    }
}

#Preview {
    RootView()
        .preferredColorScheme(.dark)
}
