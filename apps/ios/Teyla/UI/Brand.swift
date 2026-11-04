import SwiftUI

extension Health {
    var color: Color {
        switch self {
        case .offTrack: return Palette.danger
        case .atRisk: return Palette.needsYou
        case .onTrack: return Palette.primary
        case .parked: return Palette.textSecondary
        }
    }
}

extension PlatformState {
    var color: Color {
        switch self {
        case .blocked: return Palette.danger
        case .behind: return Palette.needsYou
        default: return Palette.textSecondary
        }
    }
}
