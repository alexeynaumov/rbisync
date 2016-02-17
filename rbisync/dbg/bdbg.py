# -*- coding: utf-8 -*-

# Copyright (C) 2015,2016 Alexey Naumov <rocketbuzzz@gmail.com>
#
# This file is part of rbisync.
#
# rserial is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 2 of the License, or (at
# your option) any later version.
#
# This program is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import sys
import os
sys.path.append(os.path.abspath("../../"))

print os.getcwd()

from PyQt4.QtGui import QApplication
from Dialog import Dialog

def main():
    application = QApplication(sys.argv)

    dialog = Dialog()
    dialog.show()

    sys.exit(application.exec_())

if __name__ == "__main__":
    main()
