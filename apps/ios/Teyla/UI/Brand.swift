import SwiftUI
import UIKit

/// The brand's semantic colours (brand/tokens.json), one value per appearance. Every pair passes
/// WCAG AA on the system grouped backgrounds. A status is always paired with a word and a symbol.
extension Color {
    static func brand(light: UInt32, dark: UInt32) -> Color {
        Color(uiColor: UIColor { traits in
            let hex = traits.userInterfaceStyle == .dark ? dark : light
            return UIColor(red: CGFloat((hex >> 16) & 0xFF) / 255, green: CGFloat((hex >> 8) & 0xFF) / 255,
                           blue: CGFloat(hex & 0xFF) / 255, alpha: 1)
        })
    }

    /// Off track, blocked, failed.
    static let brandDanger = brand(light: 0xB42318, dark: 0xF87166)
    /// "Needs you": at risk, behind, waiting.
    static let brandAmber = brand(light: 0xA65400, dark: 0xF2B04B)
    /// On track and the app tint.
    static let brandPrimary = brand(light: 0x3A4AA8, dark: 0x9AA7F2)
}

extension Health {
    var color: Color {
        switch self {
        case .offTrack: return .brandDanger
        case .atRisk: return .brandAmber
        case .onTrack: return .brandPrimary
        case .parked: return .secondary
        }
    }
}

extension PlatformState {
    var color: Color {
        switch self {
        case .blocked: return .brandDanger
        case .behind: return .brandAmber
        default: return .secondary
        }
    }
}
