/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        apple: {
          canvas: "#f5f5f7",
          raised: "#fbfbfd",
          panel: "#ffffff",
          ink: "#1d1d1f",
          muted: "#6e6e73",
          soft: "#86868b",
          hairline: "#d2d2d7",
          line: "rgb(60 60 67 / 0.14)",
          blue: "#0071e3",
          blueHover: "#0077ed",
          blueSoft: "#e8f2ff",
          green: "#008a22",
          greenSoft: "#eaf7ed",
          red: "#d70015",
          redSoft: "#fff0f1",
          yellow: "#b26a00",
          yellowSoft: "#fff7e6",
        },
      },
      boxShadow: {
        apple: "0 1px 2px rgb(0 0 0 / 0.04), 0 10px 28px rgb(0 0 0 / 0.05)",
        "apple-lg": "0 1px 2px rgb(0 0 0 / 0.06), 0 18px 44px rgb(0 0 0 / 0.08)",
        "apple-blue": "0 8px 18px rgb(0 113 227 / 0.18)",
      },
      fontFamily: {
        sans: [
          "-apple-system",
          "BlinkMacSystemFont",
          '"SF Pro Text"',
          '"SF Pro Display"',
          '"Segoe UI"',
          "system-ui",
          "sans-serif",
        ],
      },
    },
  },
  plugins: [],
};
