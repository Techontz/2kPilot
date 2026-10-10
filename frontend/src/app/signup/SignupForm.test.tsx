import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { SignupForm } from "./SignupForm";

const replace = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ replace }) }));

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

async function fillForm() {
  await userEvent.type(screen.getByLabelText("Name"), "Ada");
  await userEvent.type(screen.getByLabelText("Email"), "ada@example.com");
  await userEvent.type(screen.getByLabelText(/^Password/), "Correct-Horse-1");
  await userEvent.type(screen.getByLabelText("Confirm password"), "Correct-Horse-1");
}

describe("SignupForm", () => {
  const fetchMock = vi.fn<typeof fetch>();
  beforeEach(() => vi.stubGlobal("fetch", fetchMock));
  afterEach(() => {
    vi.unstubAllGlobals();
    fetchMock.mockReset();
    replace.mockReset();
  });

  it("keeps submit disabled until the risk acknowledgement is ticked", async () => {
    render(<SignupForm />);
    const submit = screen.getByRole("button", { name: "Create account" });
    expect(submit).toBeDisabled();
    await userEvent.click(screen.getByRole("checkbox", { name: /I may lose my entire balance/ }));
    expect(submit).toBeEnabled();
  });

  it("registers with accept_terms and goes to the dashboard", async () => {
    fetchMock.mockImplementation(async (input) =>
      String(input).includes("csrf-cookie") ? new Response(null, { status: 204 }) : json(201, { user: { id: "u-1" } }),
    );
    render(<SignupForm />);
    await fillForm();
    await userEvent.click(screen.getByRole("checkbox", { name: /I may lose my entire balance/ }));
    await userEvent.click(screen.getByRole("button", { name: "Create account" }));

    const call = fetchMock.mock.calls.find(([url]) => String(url) === "/api/auth/register");
    expect(JSON.parse(String(call?.[1]?.body))).toEqual({
      name: "Ada", email: "ada@example.com", password: "Correct-Horse-1", password_confirmation: "Correct-Horse-1", accept_terms: true,
    });
    expect(replace).toHaveBeenCalledWith("/");
  });

  it("shows server field errors next to the field", async () => {
    fetchMock.mockImplementation(async (input) =>
      String(input).includes("csrf-cookie")
        ? new Response(null, { status: 204 })
        : json(422, { message: "The email has already been taken.", errors: { email: ["The email has already been taken."] } }),
    );
    render(<SignupForm />);
    await fillForm();
    await userEvent.click(screen.getByRole("checkbox", { name: /I may lose my entire balance/ }));
    await userEvent.click(screen.getByRole("button", { name: "Create account" }));

    expect(await screen.findByText("The email has already been taken.")).toBeInTheDocument();
    expect(replace).not.toHaveBeenCalled();
  });

  it("shows the server message when registration is disabled", async () => {
    fetchMock.mockImplementation(async (input) =>
      String(input).includes("csrf-cookie")
        ? new Response(null, { status: 204 })
        : json(403, { message: "Registration is closed.", code: "registration_disabled" }),
    );
    render(<SignupForm />);
    await fillForm();
    await userEvent.click(screen.getByRole("checkbox", { name: /I may lose my entire balance/ }));
    await userEvent.click(screen.getByRole("button", { name: "Create account" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Registration is closed.");
  });
});
