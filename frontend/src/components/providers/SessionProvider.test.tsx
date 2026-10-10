import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/api";
import { loginUrl, SessionProvider } from "./SessionProvider";

const replace = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ replace }) }));
const api = vi.fn();
vi.mock("@/lib/api", async (orig) => ({ ...(await orig<typeof import("@/lib/api")>()), api: (...args: unknown[]) => api(...args) }));

const USER = { id: "u1", name: "Ada", email: "ada@example.com", role: "user", mfa_enabled: false, mfa_required: false, last_login_at: null };

beforeEach(() => {
  replace.mockClear();
  api.mockReset();
  vi.useFakeTimers();
});
afterEach(() => vi.useRealTimers());

describe("loginUrl", () => {
  it("keeps the query string in next=", () => {
    expect(loginUrl({ pathname: "/settings", search: "?tab=brokers" })).toBe("/login?next=%2Fsettings%3Ftab%3Dbrokers");
    expect(loginUrl({ pathname: "/history", search: "" })).toBe("/login?next=%2Fhistory");
    expect(loginUrl({ pathname: "/", search: "" })).toBe("/login");
  });
});

describe("SessionProvider", () => {
  it("does not sign the user out when the server is briefly unreachable", async () => {
    const down = new ApiError(0, "network_error", "Cannot reach the 2kPilot server.");
    api.mockRejectedValueOnce(down).mockRejectedValueOnce(down).mockRejectedValueOnce(down).mockRejectedValueOnce(down)
      .mockRejectedValueOnce(down).mockRejectedValueOnce(down).mockResolvedValueOnce({ user: USER });
    render(<SessionProvider><p>dashboard</p></SessionProvider>);
    await act(async () => vi.advanceTimersByTimeAsync(10_000));
    expect(screen.getByText(/Can.t reach the 2kPilot server/)).toBeInTheDocument();
    await act(async () => vi.advanceTimersByTimeAsync(60_000));
    expect(screen.getByText("dashboard")).toBeInTheDocument();
    expect(replace).not.toHaveBeenCalled();
  });

  it("sends a signed-out user to the sign-in page, keeping where they were", async () => {
    window.history.replaceState(null, "", "/settings?tab=risk");
    api.mockRejectedValue(new ApiError(401, "http_error", "Unauthenticated."));
    render(<SessionProvider><p>dashboard</p></SessionProvider>);
    await act(async () => vi.advanceTimersByTimeAsync(10));
    expect(replace).toHaveBeenCalledWith("/login?next=%2Fsettings%3Ftab%3Drisk");
    window.history.replaceState(null, "", "/");
  });
});
