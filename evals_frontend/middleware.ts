import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

const AUTH_PATHS = ["/login", "/signup"];
const PUBLIC_PATHS = [...AUTH_PATHS, "/landing"];

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;
  const isAuthPath = AUTH_PATHS.some((p) => pathname.startsWith(p));
  const isPublic = PUBLIC_PATHS.some((p) => pathname.startsWith(p));
  const token = request.cookies.get("evalra_token")?.value;

  if (isPublic) {
    if (isAuthPath && token) return NextResponse.redirect(new URL("/dashboard", request.url));
    return NextResponse.next();
  }

  if (!token) {
    return NextResponse.redirect(new URL("/login", request.url));
  }

  return NextResponse.next();
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
