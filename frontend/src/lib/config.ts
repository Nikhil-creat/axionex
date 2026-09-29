export const DEMO = process.env.NEXT_PUBLIC_DEMO_MODE === "true";
export const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
export const V1 = `${API}/api/v1`;
export const inr = new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 });
