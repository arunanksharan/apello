module.exports = {
  apps: [
    {
      name: 'pipecat-mosaic-agent', // Name for PM2 list
      script: './mosaic/bot.py', // Path to script (relative to cwd)
      //   args: 'start', // No extra args needed for the script itself
      cwd: '/Users/paruljuniwal/kuzushi_labs/apello/demo_pipecat', // *** SET ABSOLUTE PATH to your project ***
      interpreter:
        '/Users/paruljuniwal/kuzushi_labs/apello/demo_pipecat/apello_dpc/bin/python', // *** SET ABSOLUTE PATH to python in your venv ***
      log_date_format: 'YYYY-MM-DD HH:mm:ss Z',
    },
  ],
};
