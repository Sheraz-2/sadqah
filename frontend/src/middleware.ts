import { NextResponse, type NextRequest } from "next/server";

// Coarse gate only: the API re-checks the session and role on every call (this just avoids flashing a portal to signed-out visitors).
export function middleware(req: NextRequest) {
  if (!req.cookies.get("sq_session")) {
    const url = req.nextUrl.clone();
    url.pathname = "/login";
    url.search = `?next=${encodeURIComponent(req.nextUrl.pathname)}`;
    return NextResponse.redirect(url);
  }
  return NextResponse.next();
}

export const config = { matcher: ["/dashboard/:path*", "/recipient/:path*", "/admin/:path*"] };
