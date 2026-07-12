export const environment = {
  production: true,
  // Same-origin: nginx reverse-proxies /api/* to the backend container,
  // so cookies are first-party and no CORS configuration is needed.
  apiUrl: ''
};
