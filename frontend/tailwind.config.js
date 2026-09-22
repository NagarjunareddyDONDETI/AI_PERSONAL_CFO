/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        navy: {
          // 950 is deeper than the app background — used for the marketing
          // page's nav/footer so they read as "behind" the content.
          950: "#060912",
          900: "#0a0e1a",
          800: "#0f1626",
          700: "#161f36",
        },
        teal: {
          accent: "#2dd4bf",
        },
        violet: {
          accent: "#a78bfa",
        },
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "sans-serif"],
      },
      backdropBlur: {
        xs: "2px",
      },
      keyframes: {
        pulseGlow: {
          "0%, 100%": { opacity: "0.6", transform: "scale(1)" },
          "50%": { opacity: "1", transform: "scale(1.03)" },
        },
        floaty: {
          "0%, 100%": { transform: "translateY(0px)" },
          "50%": { transform: "translateY(-8px)" },
        },
        // Marquee track is rendered twice, so -50% is one seamless loop.
        marquee: {
          "0%": { transform: "translateX(0)" },
          "100%": { transform: "translateX(-50%)" },
        },
        gradientPan: {
          "0%, 100%": { backgroundPosition: "0% 50%" },
          "50%": { backgroundPosition: "100% 50%" },
        },
        scrollCue: {
          "0%": { opacity: "0", transform: "translateY(-6px)" },
          "50%": { opacity: "1" },
          "100%": { opacity: "0", transform: "translateY(8px)" },
        },
      },
      animation: {
        pulseGlow: "pulseGlow 2s ease-in-out infinite",
        floaty: "floaty 4s ease-in-out infinite",
        marquee: "marquee 34s linear infinite",
        gradientPan: "gradientPan 8s ease-in-out infinite",
        scrollCue: "scrollCue 1.8s ease-in-out infinite",
      },
    },
  },
  plugins: [],
};
