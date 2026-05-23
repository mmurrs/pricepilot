// Vercel serverless entry — re-export the Express app from server.js.
// The Express app intentionally does NOT call .listen() in this environment;
// Vercel's @vercel/node runtime invokes the exported handler per request.
import app from "../server.js";

export default app;
