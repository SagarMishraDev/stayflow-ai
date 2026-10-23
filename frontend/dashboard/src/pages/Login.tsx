import { useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../lib/auth";
import { AUTH_401_MESSAGES, apiErrorMessage } from "../lib/api";
import { loginSchema, type LoginForm } from "../lib/schemas";
import { Field, FormError, TextInput } from "../components/Form";

export default function Login() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const [serverError, setServerError] = useState<string | null>(null);
  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<LoginForm>({ resolver: zodResolver(loginSchema) });

  async function onSubmit(values: LoginForm) {
    setServerError(null);
    try {
      await login(values.email, values.password);
      navigate("/", { replace: true });
    } catch (e) {
      const raw = apiErrorMessage(e);
      setServerError(AUTH_401_MESSAGES[raw] ?? raw);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-mist px-4 py-10">
      <div className="w-full max-w-md overflow-hidden rounded-2xl border border-line bg-paper shadow-lift">
        <div className="flex items-center gap-3 bg-deep-teal px-8 py-6">
          <span
            aria-hidden
            className="grid h-12 w-12 place-items-center rounded-xl bg-sun font-display text-3xl font-bold text-ink ring-2 ring-inset ring-ink"
          >
            S
          </span>
          <div>
            <h1 className="text-3xl font-bold leading-none text-white">StayFlow Ops</h1>
            <p className="mt-1 text-sm font-semibold text-white/75">Staff sign-in</p>
          </div>
        </div>
        <form onSubmit={handleSubmit(onSubmit)} className="space-y-4 px-8 pt-8" noValidate>
          <Field label="Email" htmlFor="email" error={errors.email?.message}>
            <TextInput
              id="email"
              name="email"
              register={register}
              type="email"
              autoComplete="username"
              placeholder="you@hotel.example"
            />
          </Field>
          <Field
            label="Password"
            htmlFor="password"
            error={errors.password?.message}
          >
            <TextInput
              id="password"
              name="password"
              register={register}
              type="password"
              autoComplete="current-password"
            />
          </Field>
          <FormError error={serverError} />
          <button type="submit" className="btn btn-primary w-full" disabled={isSubmitting}>
            {isSubmitting ? "Signing in…" : "Sign in"}
          </button>
        </form>
        <p className="px-8 pb-8 pt-4 text-xs text-ink/50">
          Sessions expire after 8 hours. Your role determines which areas of
          the console you can see.
        </p>
      </div>
    </div>
  );
}
