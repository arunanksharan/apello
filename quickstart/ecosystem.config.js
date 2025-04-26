module.exports = {
  apps: [
    {
      name: 'livekit-py-agent', // Name for PM2 list
      script: 'main.py', // Path to script (relative to cwd)
      args: 'start', // No extra args needed for the script itself
      cwd: '/root/apello/quickstart', // *** SET ABSOLUTE PATH to your project ***
      interpreter: '/root/apello/quickstart/venv/bin/python3', // *** SET ABSOLUTE PATH to python in your venv ***
      log_date_format: 'YYYY-MM-DD HH:mm:ss Z',
    },
  ],
};
