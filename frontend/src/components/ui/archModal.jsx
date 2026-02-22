import { useState, useRef } from "react";

const ACCENT = "#E85D26";
const BG_DARK = "#0F1117";
const BG_CARD = "#181B23";
const BG_CARD_HOVER = "#1F2330";
const BORDER = "#2A2E3A";
const TEXT_PRIMARY = "#E8E9ED";
const TEXT_SECONDARY = "#8B8FA3";
const TEXT_DIM = "#5C6072";
const GREEN = "#34D399";
const BLUE = "#60A5FA";
const YELLOW = "#FBBF24";
const PURPLE = "#A78BFA";
const PINK = "#F472B6";
const CYAN = "#22D3EE";

const PIPELINE_NODES = [
  {
    id: "csv",
    label: "CSV Parse",
    icon: "📄",
    color: BLUE,
    file: "csv_parser.py",
    subtitle: "155 tickets • 51 managers • 15 offices",
    bullets: [],
    dataPoints: [
      { label: "Segments", value: "Mass 96 · VIP 40 · Priority 19" },
      { label: "Cities", value: "102 unique (mostly small towns)" },
      { label: "Empty desc", value: "3/155 → default Консультация" },
      { label: "Attachments", value: "5 tickets (.png only)" },
    ],
  },
  {
    id: "IIN",
    label: "IIN Masking",
    icon: "🛡️",
    color: PURPLE,
    file: "personal_data_masking.py",
    subtitle: "8 detections • 7 tickets • 0 false positives",
    bullets: [
      "Detection → Masking → LLM Processing → Rehydration",
      "Critical for a brokerage platform — client IIN never leaves the security boundary before reaching external LLMs",
    ],
    dataPoints: [
      { label: "Phones", value: "Regex: +7/8 + 10 digits, handles partial masks (ХХХХ)" },
      { label: "IIN", value: "Regex: 12-digit Kazakhstan national ID number" },
      { label: "Card Numbers", value: "Regex: 16 digits with optional separators" },
    ],
  },
  {
    id: "spam",
    label: "Spam Pre-Filter",
    icon: "🚫",
    color: YELLOW,
    file: "spam_prefiltering.py",
    subtitle: "5/155 spam (3.2%) • 2 layers",
    bullets: [],
    dataPoints: [
      { label: "Structural", value: "3 caught (0ms each)" },
      { label: "LLM needed", value: "2 caught (~300ms each)" },
      { label: "\"Help\" (row 26)", value: "4 chars → LLM → NOT spam ✓" },
    ],
  },
  {
    id: "llm",
    label: "LLM Analysis",
    icon: "🧠",
    color: ACCENT,
    file: "llm_processing.py",
    subtitle: "Single call → type + sentiment + language + summary + explanation",
    bullets: [],
    dataPoints: [
      { label: "Concurrency", value: "Semaphore (5 parallel)" },
      { label: "Spam guard", value: "Already flagged → skip LLM" },
      { label: "Edge case", value: "Row 132: Uzbek Latin → age-based" },
    ],
  },
  {
    id: "geo",
    label: "Geocoding",
    icon: "📍",
    color: GREEN,
    file: "geocoder.py",
    subtitle: "2GIS primary → Nominatim fallback • in-memory cache",
    bullets: [
      "Runs in PARALLEL with LLM via asyncio.gather — total latency ≈ max(LLM, Geo)",
      "Address cascade: full address → city center → capital center → CIS country search → Astana/Almaty 50/50 fallback",
    ],
    dataPoints: [
      { label: "Providers", value: "2GIS → Nominatim → fallback" },
    ],
  },
  {
    id: "priority",
    label: "Priority Scoring",
    icon: "⚡",
    color: PINK,
    file: "priority.py",
    subtitle: "Weighted formula → 1.0–10.0 scale",
    bullets: [
      "Segment 30% · Type 25% · Sentiment 15% · Age 10% · Repeat 7%",
      "Fraud floor: Мошенничество always ≥ 8.0",
      "Additive extras:",
      "  • FIFO (+0–1pt) — earlier registration → earlier processing, fair queue order",
      "  • Expansion country (+1pt) — justify marketing & expansion investment, prioritize new-market clients (Pakistan, US, UAE, Turkey…)",
      "  • Young VIP (+1pt, age <30 & VIP) — high-potential lifetime value, retain early adopters with premium service",
    ],
    dataPoints: [
      { label: "Scale", value: "1.0 – 10.0 (clamped)" },
      { label: "Fraud floor", value: "Min 8.0 for fraud" },
    ],
  },
  {
    id: "routing",
    label: "Routing Engine",
    icon: "🔀",
    color: CYAN,
    file: "routing.py + geo.py + skills.py",
    subtitle: "Geo filter → Skill filter → Lowest-load assignment",
    bullets: [
      "Step 1 — Geo Filter:",
      "  • Haversine distance ticket ↔ each office",
      "  • Threshold: closest × 1.5, floor 50km",
      "  • No coords → all managers pass through",
      "Step 2 — Skill Filter:",
      "  • VIP/Priority → needs VIP skill",
      "  • Смена данных → must be Главный специалист",
      "  • KZ/ENG language → needs matching skill",
      "  • Relaxation cascade: drop lang → position → VIP",
      "Step 3 — Assignment:",
      "  • Process tickets by priority (highest first)",
      "  • Assign to lowest-load eligible manager",
      "  • Load = Σ difficulty weights of assigned tickets",
    ],
    dataPoints: [
      { label: "Managers", value: "51 across 15 offices" },
      { label: "Positions", value: "Вед=24, Глав=16, Спец=11" },
      { label: "VIP-skilled", value: "20/51 managers" },
    ],
  },
];

function NodeCard({ node, expanded, onToggle }) {
  const isExpanded = expanded === node.id;
  const hasMore = node.dataPoints.length > 1 || node.bullets.length > 0;

  return (
    <div
      style={{
        background: isExpanded ? BG_CARD_HOVER : BG_CARD,
        border: `1px solid ${isExpanded ? node.color : BORDER}`,
        borderRadius: 12,
        padding: "14px 16px",
        cursor: hasMore ? "pointer" : "default",
        transition: "all 0.25s ease",
        boxShadow: isExpanded
          ? `0 0 24px ${node.color}22, 0 4px 20px rgba(0,0,0,0.4)`
          : "0 2px 8px rgba(0,0,0,0.3)",
        position: "relative",
        overflow: "hidden",
      }}
      onClick={() => hasMore && onToggle(isExpanded ? null : node.id)}
    >
      <div style={{
        position: "absolute", top: 0, left: 0, right: 0, height: 3,
        background: `linear-gradient(90deg, ${node.color}, ${node.color}88, transparent)`,
      }} />

      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 6 }}>
        <span style={{ fontSize: 20 }}>{node.icon}</span>
        <span style={{
          fontFamily: "'JetBrains Mono', monospace", fontWeight: 700,
          fontSize: 15, color: TEXT_PRIMARY, letterSpacing: "-0.02em",
        }}>{node.label}</span>
        <span style={{
          marginLeft: "auto", fontSize: 11, color: node.color,
          fontFamily: "'JetBrains Mono', monospace", opacity: 0.8,
        }}>{node.file}</span>
      </div>

      <div style={{
        fontSize: 12, color: TEXT_SECONDARY,
        fontFamily: "'Space Grotesk', sans-serif",
        lineHeight: 1.4, marginBottom: 10,
      }}>{node.subtitle}</div>

      {node.dataPoints.length > 0 && (
        <div style={{
          background: `${node.color}12`, border: `1px solid ${node.color}30`,
          borderRadius: 8, padding: "6px 10px",
        }}>
          <div style={{
            fontSize: 10, color: node.color,
            fontFamily: "'JetBrains Mono', monospace",
            textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 2,
          }}>{node.dataPoints[0].label}</div>
          <div style={{
            fontSize: 12, color: TEXT_PRIMARY,
            fontFamily: "'Space Grotesk', sans-serif",
          }}>{node.dataPoints[0].value}</div>
        </div>
      )}

      {isExpanded && (
        <div style={{ animation: "fadeSlideIn 0.3s ease" }}>
          {node.dataPoints.length > 1 && (
            <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginTop: 8 }}>
              {node.dataPoints.slice(1).map((dp, i) => (
                <div key={i} style={{
                  background: `${node.color}12`, border: `1px solid ${node.color}30`,
                  borderRadius: 8, padding: "6px 10px", flex: "1 1 auto", minWidth: 140,
                }}>
                  <div style={{
                    fontSize: 10, color: node.color,
                    fontFamily: "'JetBrains Mono', monospace",
                    textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 2,
                  }}>{dp.label}</div>
                  <div style={{
                    fontSize: 12, color: TEXT_PRIMARY,
                    fontFamily: "'Space Grotesk', sans-serif",
                  }}>{dp.value}</div>
                </div>
              ))}
            </div>
          )}

          {node.bullets.length > 0 && (
            <div style={{ borderTop: `1px solid ${BORDER}`, paddingTop: 10, marginTop: 12 }}>
              {node.bullets.map((b, i) => {
                const isIndented = b.startsWith("  •");
                return (
                  <div key={i} style={{
                    fontSize: 12,
                    color: isIndented ? TEXT_SECONDARY : TEXT_PRIMARY,
                    fontFamily: "'Space Grotesk', sans-serif",
                    lineHeight: 1.7, paddingLeft: isIndented ? 16 : 0,
                    display: "flex", gap: 6,
                  }}>
                    {!isIndented && <span style={{ color: node.color, flexShrink: 0 }}>›</span>}
                    <span>{b}</span>
                  </div>
                );
              })}
            </div>
          )}

          <div style={{
            marginTop: 10, textAlign: "center", fontSize: 11,
            color: TEXT_DIM, fontFamily: "'JetBrains Mono', monospace",
          }}>click to collapse</div>
        </div>
      )}

      {!isExpanded && hasMore && (
        <div style={{
          marginTop: 8, fontSize: 11, color: TEXT_DIM,
          fontFamily: "'JetBrains Mono', monospace", textAlign: "center",
        }}>see more ↓</div>
      )}
    </div>
  );
}

export default function ArchitectureModal() {
  const [isOpen, setIsOpen] = useState(false);
  const [expanded, setExpanded] = useState(null);
  const panelRef = useRef(null);

  return (
    <>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;700&family=Space+Grotesk:wght@400;500;600;700&display=swap');
        @keyframes fadeSlideIn {
          from { opacity: 0; transform: translateY(-8px); }
          to { opacity: 1; transform: translateY(0); }
        }
        @keyframes slideIn {
          from { transform: translateX(100%); }
          to { transform: translateX(0); }
        }
        @keyframes pulse {
          0%, 100% { box-shadow: 0 0 0 0 ${ACCENT}44; }
          50% { box-shadow: 0 0 0 8px ${ACCENT}00; }
        }
        .arch-scroll::-webkit-scrollbar { width: 6px; }
        .arch-scroll::-webkit-scrollbar-track { background: transparent; }
        .arch-scroll::-webkit-scrollbar-thumb { background: ${BORDER}; border-radius: 3px; }
      `}</style>

      {!isOpen && (
        <button onClick={() => setIsOpen(true)} style={{
          position: "fixed", right: 20, top: "50%", transform: "translateY(-50%)",
          zIndex: 9999, background: `linear-gradient(135deg, ${ACCENT}, ${ACCENT}cc)`,
          color: "#fff", border: "none", borderRadius: 12, padding: "14px 16px",
          cursor: "pointer", fontFamily: "'JetBrains Mono', monospace",
          fontSize: 13, fontWeight: 600, display: "flex", flexDirection: "column",
          alignItems: "center", gap: 6, boxShadow: `0 4px 20px ${ACCENT}44`,
          animation: "pulse 2.5s ease infinite",
          writingMode: "vertical-rl", textOrientation: "mixed", letterSpacing: "0.05em",
        }}>
          <span style={{ writingMode: "horizontal-tb", fontSize: 18, marginBottom: 4 }}>🏗️</span>
          <span>ARCH</span>
        </button>
      )}

      {isOpen && (
        <div style={{
          position: "fixed", top: 0, left: 0, right: 0, bottom: 0,
          zIndex: 10000, display: "flex", justifyContent: "flex-end",
        }}>
          <div
            onClick={() => setIsOpen(false)}
            style={{
              position: "absolute", inset: 0,
              background: "rgba(0,0,0,0.5)", backdropFilter: "blur(4px)",
            }}
          />
          <div style={{
            position: "relative",
            width: "min(520px, 92vw)", height: "100vh",
            display: "flex", flexDirection: "column",
            background: BG_DARK, borderLeft: `1px solid ${BORDER}`,
            boxShadow: "-8px 0 40px rgba(0,0,0,0.6)",
            animation: "slideIn 0.35s cubic-bezier(0.16, 1, 0.3, 1)",
          }}>
            <div style={{
              padding: "16px 20px", borderBottom: `1px solid ${BORDER}`,
              display: "flex", alignItems: "center", justifyContent: "space-between",
              background: `${BG_DARK}ee`, backdropFilter: "blur(12px)", flexShrink: 0,
            }}>
              <div>
                <div style={{
                  fontFamily: "'JetBrains Mono', monospace", fontWeight: 700,
                  fontSize: 18, color: TEXT_PRIMARY, letterSpacing: "-0.02em",
                }}>
                  <span style={{ color: ACCENT }}>F.I.R.E.</span> Architecture
                </div>
                <div style={{
                  fontFamily: "'Space Grotesk', sans-serif", fontSize: 12,
                  color: TEXT_DIM, marginTop: 2,
                }}>Freedom Intelligent Routing Engine</div>
              </div>
              <button onClick={() => setIsOpen(false)} style={{
                background: "none", border: `1px solid ${BORDER}`, color: TEXT_SECONDARY,
                borderRadius: 8, width: 34, height: 34, cursor: "pointer", fontSize: 16,
                display: "flex", alignItems: "center", justifyContent: "center",
              }}>✕</button>
            </div>

            <div style={{
              textAlign: "center", padding: "12px 20px",
              borderBottom: `1px solid ${BORDER}`, flexShrink: 0,
            }}>
              <div style={{
                display: "flex", alignItems: "center", justifyContent: "center",
                gap: 6, flexWrap: "wrap",
              }}>
                {["CSV", "→", "IIN", "→", "Spam", "→"].map((t, i) => (
                  <span key={i} style={{
                    fontFamily: "'JetBrains Mono', monospace", fontSize: 13,
                    color: t === "→" ? TEXT_DIM : TEXT_PRIMARY,
                    fontWeight: t === "→" ? 400 : 600,
                  }}>{t}</span>
                ))}
                <span style={{
                  fontFamily: "'JetBrains Mono', monospace", fontSize: 12,
                  color: ACCENT, background: `${ACCENT}15`,
                  border: `1px solid ${ACCENT}30`, borderRadius: 6, padding: "2px 8px",
                }}>LLM ‖ Geo</span>
                {["→", "Priority", "→", "Route"].map((t, i) => (
                  <span key={`b${i}`} style={{
                    fontFamily: "'JetBrains Mono', monospace", fontSize: 13,
                    color: t === "→" ? TEXT_DIM : TEXT_PRIMARY,
                    fontWeight: t === "→" ? 400 : 600,
                  }}>{t}</span>
                ))}
              </div>
            </div>

            <div ref={panelRef} className="arch-scroll" style={{
              flex: 1, overflowY: "auto", padding: "12px 12px 32px",
            }}>
              <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                {PIPELINE_NODES.map((node) => (
                  <NodeCard key={node.id} node={node} expanded={expanded} onToggle={setExpanded} />
                ))}
              </div>

              <div style={{
                marginTop: 20, background: BG_CARD,
                border: `1px solid ${BORDER}`, borderRadius: 12, padding: 16,
              }}>
                <div style={{
                  fontFamily: "'JetBrains Mono', monospace", fontSize: 13,
                  fontWeight: 700, color: TEXT_PRIMARY, marginBottom: 10,
                }}>📊 Dataset Summary</div>
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
                  {[
                    { l: "Tickets", v: "155 total", c: BLUE },
                    { l: "Managers", v: "51 / 15 offices", c: GREEN },
                    { l: "Spam", v: "5 detected (3.2%)", c: YELLOW },
                    { l: "IIN", v: "8 phones masked", c: PURPLE },
                    { l: "Languages", v: "135 RU·12 KZ·8 EN", c: CYAN },
                    { l: "Segments", v: "M96 · V40 · P19", c: PINK },
                  ].map((item, i) => (
                    <div key={i} style={{
                      display: "flex", justifyContent: "space-between", alignItems: "center",
                      padding: "6px 0", borderBottom: `1px solid ${BORDER}`,
                    }}>
                      <span style={{
                        fontSize: 12, color: item.c,
                        fontFamily: "'JetBrains Mono', monospace",
                      }}>{item.l}</span>
                      <span style={{
                        fontSize: 12, color: TEXT_SECONDARY,
                        fontFamily: "'Space Grotesk', sans-serif",
                      }}>{item.v}</span>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>
        </div>
      )}
    </>
  );
}