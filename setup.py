from distutils.core import setup

setup(name="rbisync",
      version="1.1.1",
      author = "Alexey Naumov",
      author_email = "rocketbuzzz@gmail.com",
      description = "",
      packages=["rbisync", "bdbg"],
      package_data = {
          'bdbg': [
              'icons/*',
          ],
      },      
      scripts=["bdbg/bdbg"]
)
