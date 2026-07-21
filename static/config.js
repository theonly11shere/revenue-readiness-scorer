window.TRILLOKA_CONFIG = {
  site: {
    name: "Trilloka",
    tagline: "Revenue Readiness Systems",
    brand: "TRILLOKA",
    year: 2026,
    adminPasswordHash: "8e1712a523ffc076094b78b261374b7f",
    confirmPasswordHash: "8e1712a523ffc076094b78b261374b7f",
    nav: {
      links: [
        { label: "Home", href: "index.html" },
        { label: "Solutions", href: "solutions.html" },
        { label: "Vlog", href: "vlog.html" },
        { label: "Contact", href: "contact.html" }
      ]
    },
    footer: {
      copy: "Revenue Readiness Systems",
      links: [
        { label: "Home", href: "index.html" },
        { label: "Solutions", href: "solutions.html" },
        { label: "Vlog", href: "vlog.html" },
        { label: "Contact", href: "contact.html" }
      ]
    }
  },
  pages: [
    {
      id: "index",
      title: "Trilloka — Revenue Readiness Systems",
      file: "index.html",
      theme: "dark",
      meta: {
        description: "Trilloka helps SMBs build a powerful online presence, diagnose revenue blockers, and unlock growth with Revenue Readiness Systems.",
        keywords: "SMB, online presence, revenue readiness, website scanner, conversion"
      },
      sections: [
        { id: "hero", type: "hero", order: 1, enabled: true, content: { headline: "Your site earns nothing while it looks like everyone else.", subhead: "We diagnose why visitors don't convert — then rebuild your digital presence into a revenue engine." } },
        { id: "problems", type: "problem-discovery", order: 2, enabled: true, content: { title: "Most sites fail before they start", subtitle: "Four invisible forces kill revenue before a visitor reads your first word." } },
        { id: "rrs-demo", type: "rrs-scorer", order: 3, enabled: true, content: { domain: "anhandchi.com", scores: { template: 89, sameness: 5, visualTwin: 0, presence: 0 } } },
        { id: "solutions", type: "solutions-bridge", order: 4, enabled: true, content: { title: "Four systems. One outcome: revenue." } },
        { id: "vault", type: "vault-entrance", order: 5, enabled: true, content: { title: "Behind the builds.", desc: "Raw process, failed experiments, and the systems that actually work. No fluff. No funnels." } }
      ]
    },
    {
      id: "frontend",
      title: "Revenue Readiness Scanner — Trilloka",
      file: "frontend.html",
      theme: "dark",
      meta: { description: "Run a free 4-point revenue readiness scan on any website." },
      sections: [
        { id: "rrs-results", type: "rrs-results", order: 1, enabled: true, content: { domain: "anhandchi.com" } },
        { id: "rrs-scanner", type: "rrs-scanner", order: 2, enabled: true, content: { placeholder: "https://yourdomain.com" } }
      ]
    },
    {
      id: "solutions",
      title: "Solutions — Trilloka",
      file: "solutions.html",
      theme: "dark",
      meta: { description: "Six systems designed to turn your digital presence into a revenue engine." },
      sections: [
        { id: "solutions-hero", type: "hero-small", order: 1, enabled: true, content: { title: "Solutions that scale revenue." } },
        { id: "solutions-grid", type: "solutions-grid", order: 2, enabled: true, content: {} }
      ]
    },
    {
      id: "vlog",
      title: "The Vault — Trilloka",
      file: "vlog.html",
      theme: "dark",
      meta: { description: "The Architect's Journal. Raw notes from the studio." },
      sections: []
    },
    {
      id: "contact",
      title: "Contact — Trilloka",
      file: "contact.html",
      theme: "dark",
      meta: { description: "Get in touch with Trilloka." },
      sections: []
    },
    {
      id: "admin",
      title: "Trilloka Admin",
      file: "admin.html",
      theme: "dark",
      meta: { description: "Admin panel for Trilloka." },
      sections: []
    }
  ],
  themes: {
    dark: {
      name: "Dark Gold",
      colors: {
        bg: "#0D0D0D",
        surface: "#11110e",
        surface2: "#1a1a14",
        gold: "#D4AF37",
        goldDim: "#a08020",
        goldBright: "#F5E6C8",
        teal: "#3c8c9a",
        tealDim: "#2a6a75",
        silver: "#a0a0a0",
        text: "#F5E6C8",
        textSecondary: "#b0a080",
        textMuted: "#6a6040",
        border: "#1f1f18",
        borderLight: "#2a2a1a",
        bad: "#E74C3C",
        good: "#2ECC71",
        warn: "#D4AF37"
      },
      fonts: {
        heading: "'Cormorant Garamond', serif",
        body: "'DM Sans', sans-serif"
      }
    }
  },
  tools: [
    { id: "template-liberation", name: "Template Liberation", description: "Break free from generic frameworks with custom architecture.", category: "web", icon: "", link: "solutions.html", enabled: true },
    { id: "voice-distillation", name: "Voice Distillation", description: "Replace clichés with language that only you could write.", category: "marketing", icon: "", link: "solutions.html", enabled: true },
    { id: "visual-dna", name: "Visual DNA", description: "Own a layout that no competitor can replicate.", category: "web", icon: "", link: "solutions.html", enabled: true },
    { id: "presence-engine", name: "Presence Engine", description: "Build social proof and brand signals across the web.", category: "marketing", icon: "", link: "solutions.html", enabled: true },
    { id: "conversion-loop", name: "Conversion Loop", description: "Turn every visitor into a measurable revenue event.", category: "analytics", icon: "", link: "solutions.html", enabled: true },
    { id: "retention-vault", name: "Retention Vault", description: "Keep customers returning with systems, not hope.", category: "automation", icon: "", link: "solutions.html", enabled: true }
  ]
};
