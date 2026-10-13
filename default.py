"""RunScript entry point: RunScript(service.denonavr,<action>[,<arg>])

    volume_up, volume_down     one step (Settings > Volume), never above the cap
    volume,<dB>                e.g. volume,-35
    mute[,on|off|toggle]
    power[,on|off|toggle]
    status                     a dialog with what the receiver is doing (default)
    osd                        the OSD's receiver menu: format, volume, mute
"""

import sys

from resources.lib.script import main

if __name__ == "__main__":
    main(sys.argv)
