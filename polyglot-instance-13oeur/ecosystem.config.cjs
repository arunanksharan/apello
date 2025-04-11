// /opt/livekit-node-agent/ecosystem.config.js

module.exports = {
  apps : [{
    name   : "livekit-node-agent",    // Descriptive name for PM2 list
    script : "./dist/agent.js",       // Path to the compiled JS entry point (relative to cwd)
    args   : "start",                 // Argument to run in production/worker mode (instead of 'dev')
    cwd    : "/Users/paruljuniwal/kuzushi_labs/apello/polyglot-instance-13oeur", // Set the Current Working Directory for the process
    interpreter: "node",              // Specify node interpreter (good practice)
    log_date_format: "YYYY-MM-DD HH:mm:ss Z", // Optional: Log timestamp format
    // Using default PM2 log paths: ~/.pm2/logs/livekit-node-agent-*.log
    // env: {
    //   NODE_ENV: "production", // You might need to set NODE_ENV for some apps
    //   // PM2 can inject env vars, but Node.js apps often rely on loading
    //   // .env files via the 'dotenv' package based on NODE_ENV.
    //   // Ensure your .env.local has all needed keys.
    // }
  }]
};
