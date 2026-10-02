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
    <div className="flex min-h-screen items-center justify-center bg-pine-950 px-4">
      <div className="panel w-full max-w-md p-8">
        <div className="mb-6 flex items-center gap-3">
          <span
            aria-hidden
            className="grid h-12 w-12 place-items-center rounded-full bg-brass-500 font-mono text-2xl font-semibold text-pine-950"
          >
            S
          </span>
          <div>
            <h1 className="text-xl font-bold tracking-tight">StayFlow Ops</h1>
            <p className="text-sm text-ink/60">Staff sign-in</p>
          </div>
        </div>
        <form onSubmit={handleSubmit(onSubmit)} className="space-y-4" noValidate>
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
        <p className="mt-4 text-xs text-ink/50">
          Sessions expire after 8 hours. Your role determines which areas of
          the console you can see.
        </p>
      </div>
    </div>
  );
}
