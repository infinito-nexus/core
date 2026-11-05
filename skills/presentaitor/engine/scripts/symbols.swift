import AppKit

let outDir = CommandLine.arguments[1]
let specs = CommandLine.arguments.dropFirst(2)
let basePoint: CGFloat = 100
let scale: CGFloat = 3
var manifest: [String: [String: Double]] = [:]
var missing: [String] = []

let weights: [String: NSFont.Weight] = [
    "ultralight": .ultraLight, "thin": .thin, "light": .light, "regular": .regular, "medium": .medium,
    "semibold": .semibold, "bold": .bold, "heavy": .heavy, "black": .black,
]

try FileManager.default.createDirectory(atPath: outDir, withIntermediateDirectories: true)
for spec in specs {
    let parts = spec.split(separator: "@").map(String.init)
    let name = parts[0]
    let w = parts.count > 1 ? parts[1] : "regular"
    guard let weight = weights[w], let base = NSImage(systemSymbolName: name, accessibilityDescription: nil) else {
        missing.append(spec)
        continue
    }
    let config = NSImage.SymbolConfiguration(pointSize: basePoint, weight: weight)
        .applying(NSImage.SymbolConfiguration(paletteColors: [.black]))
    guard let img = base.withSymbolConfiguration(config) else { missing.append(spec); continue }
    let size = img.size
    let pw = Int((size.width * scale).rounded(.up)), ph = Int((size.height * scale).rounded(.up))
    guard let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: pw, pixelsHigh: ph, bitsPerSample: 8,
                                     samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
                                     colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0) else { continue }
    rep.size = size
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: rep)
    img.draw(in: NSRect(origin: .zero, size: size))
    NSGraphicsContext.restoreGraphicsState()
    try rep.representation(using: .png, properties: [:])!.write(to: URL(fileURLWithPath: outDir).appendingPathComponent("\(name)__\(w).png"))
    manifest["\(name)@\(w)"] = ["w": Double(size.width / basePoint), "h": Double(size.height / basePoint)]
}

let manifestURL = URL(fileURLWithPath: outDir).appendingPathComponent("manifest.json")
if let data = try? Data(contentsOf: manifestURL),
   let old = try? JSONSerialization.jsonObject(with: data) as? [String: [String: Double]] {
    manifest = old.merging(manifest) { _, new in new }
}
try JSONSerialization.data(withJSONObject: manifest, options: [.prettyPrinted, .sortedKeys]).write(to: manifestURL)
print("\(manifest.count) symbols in \(outDir)")
if !missing.isEmpty {
    FileHandle.standardError.write("not found: \(missing.joined(separator: " ")) (names as in the SF Symbols app; weights: \(weights.keys.sorted().joined(separator: ", ")))\n".data(using: .utf8)!)
    exit(1)
}
