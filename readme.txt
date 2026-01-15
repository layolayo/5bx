go to 5BX directory

sudo cp 99-garmin.rules /etc/udev/rules.d/99-garmin.rules

sudo udevadm control --reload-rules && sudo udevadm trigger
