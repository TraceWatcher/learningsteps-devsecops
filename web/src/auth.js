import { PublicClientApplication } from "@azure/msal-browser";

export const apiScopes = [
  "api://dc797bb1-a255-4714-8910-a09e876100e9/access_as_user",
];

const appUrl = `${window.location.origin}/`;

export const msalInstance = new PublicClientApplication({
  auth: {
    clientId: "0ff6b105-66c2-4848-99ac-0f57a375d499",
    authority:
      "https://login.microsoftonline.com/c0531484-50fa-4ff2-97df-b1f2d4810603",
    redirectUri: appUrl,
    postLogoutRedirectUri: appUrl,
    navigateToLoginRequestUrl: false,
  },
  cache: {
    cacheLocation: "sessionStorage",
  },
});