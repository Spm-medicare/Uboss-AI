import { ImageResponse } from "next/og";

/**
 * The browser-tab icon, generated from the same geometry as the sidebar mark.
 *
 * Generated rather than checked in as a `.ico` for the reason the mark itself is SVG: one source
 * of truth. A favicon file would be a second copy of the logo that nobody remembers to update,
 * and the first time the artwork changes the tab would keep the old one for months.
 *
 * At 32 pixels the wordmark is unreadable and the interlocked `UB` is barely legible, so this
 * draws the monogram alone on the brand ground — which is what a favicon is for: recognition in a
 * row of tabs, not reading.
 */
export const size = { width: 32, height: 32 };
export const contentType = "image/png";

export default function Icon() {
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          //  Solid black, as the artwork is. A transparent favicon disappears against a dark tab
          //  strip, which is exactly where somebody is looking for it.
          background: "#0a0a0a",
          borderRadius: 6,
        }}
      >
        <svg width="24" height="18" viewBox="0 0 420 310" fill="#ffffff">
          <path d="M22 8 V203 a93 93 0 0 0 186 0 V8 H150 V203 a35 35 0 0 1-70 0 V8 Z" />
          <path
            fillRule="evenodd"
            d={
              "M196 62 L256 8 H318 a72 72 0 0 1 0 144 H330 a72 72 0 0 1 0 144 H196 Z" +
              "M256 54 H300 a37 37 0 0 1 0 75 H256 Z" +
              "M256 175 H312 a37 37 0 0 1 0 75 H256 Z"
            }
          />
        </svg>
      </div>
    ),
    size,
  );
}
