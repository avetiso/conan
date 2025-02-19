from conan.tools._check_build_profile import check_using_build_profile
from conan.tools._compilers import architecture_flag, build_type_flags, cppstd_flag, \
    build_type_link_flags
from conan.tools.apple.apple import apple_min_version_flag, to_apple_arch, \
    apple_sdk_path
from conan.tools.build.cross_building import cross_building, get_cross_building_settings
from conan.tools.env import Environment
from conan.tools.files.files import save_toolchain_args
from conan.tools.gnu.get_gnu_triplet import _get_gnu_triplet
from conan.tools.microsoft import VCVars, is_msvc
from conans.tools import args_to_string


class AutotoolsToolchain:
    def __init__(self, conanfile, namespace=None):
        self._conanfile = conanfile
        self._namespace = namespace
        build_type = self._conanfile.settings.get_safe("build_type")

        self.configure_args = []
        self.make_args = []
        self.default_configure_install_args = True

        # TODO: compiler.runtime for Visual studio?
        # defines
        self.ndebug = None
        if build_type in ['Release', 'RelWithDebInfo', 'MinSizeRel']:
            self.ndebug = "NDEBUG"
        self.gcc_cxx11_abi = self._cxx11_abi_define()
        self.defines = []

        # cxxflags, cflags
        self.cxxflags = []
        self.cflags = []
        self.ldflags = []
        self.libcxx = self._libcxx()
        self.fpic = self._conanfile.options.get_safe("fPIC")

        self.cppstd = cppstd_flag(self._conanfile.settings)
        self.arch_flag = architecture_flag(self._conanfile.settings)
        # TODO: This is also covering compilers like Visual Studio, necessary to test it (&remove?)
        self.build_type_flags = build_type_flags(self._conanfile.settings)
        self.build_type_link_flags = build_type_link_flags(self._conanfile.settings)

        # Cross build
        self._host = None
        self._build = None
        self._target = None

        self.apple_arch_flag = self.apple_isysroot_flag = None
        self.apple_min_version_flag = apple_min_version_flag(self._conanfile)

        self.msvc_runtime_flag = self._get_msvc_runtime_flag()

        if cross_building(self._conanfile):
            os_build, arch_build, os_host, arch_host = get_cross_building_settings(self._conanfile)
            compiler = self._conanfile.settings.get_safe("compiler")
            self._host = _get_gnu_triplet(os_host, arch_host, compiler=compiler)
            self._build = _get_gnu_triplet(os_build, arch_build, compiler=compiler)

            # Apple Stuff
            if os_build == "Macos":
                sdk_path = apple_sdk_path(conanfile)
                apple_arch = to_apple_arch(self._conanfile.settings.get_safe("arch"))
                # https://man.archlinux.org/man/clang.1.en#Target_Selection_Options
                self.apple_arch_flag = "-arch {}".format(apple_arch) if apple_arch else None
                # -isysroot makes all includes for your library relative to the build directory
                self.apple_isysroot_flag = "-isysroot {}".format(sdk_path) if sdk_path else None

        check_using_build_profile(self._conanfile)

    def _get_msvc_runtime_flag(self):
        msvc_runtime_flag = None
        if self._conanfile.settings.get_safe("compiler") == "msvc":
            runtime_type = self._conanfile.settings.get_safe("compiler.runtime_type")
            if runtime_type == "Release":
                values = {"static": "MT", "dynamic": "MD"}
            else:
                values = {"static": "MTd", "dynamic": "MDd"}
            runtime = values.get(self._conanfile.settings.get_safe("compiler.runtime"))
            if runtime:
                msvc_runtime_flag = "-{}".format(runtime)
        elif self._conanfile.settings.get_safe("compiler") == "Visual Studio":
            runtime = self._conanfile.settings.get_safe("compiler.runtime")
            if runtime:
                msvc_runtime_flag = "-{}".format(runtime)

        return msvc_runtime_flag

    def _cxx11_abi_define(self):
        # https://gcc.gnu.org/onlinedocs/libstdc++/manual/using_dual_abi.html
        # The default is libstdc++11, only specify the contrary '_GLIBCXX_USE_CXX11_ABI=0'
        settings = self._conanfile.settings
        libcxx = settings.get_safe("compiler.libcxx")
        if not libcxx:
            return

        compiler = settings.get_safe("compiler.base") or settings.get_safe("compiler")
        if compiler in ['clang', 'apple-clang', 'gcc']:
            if libcxx == 'libstdc++':
                return '_GLIBCXX_USE_CXX11_ABI=0'
            elif libcxx == "libstdc++11" and self._conanfile.conf.get("tools.gnu:define_libcxx11_abi",
                                                                      check_type=bool):
                return '_GLIBCXX_USE_CXX11_ABI=1'

    def _libcxx(self):
        settings = self._conanfile.settings
        libcxx = settings.get_safe("compiler.libcxx")
        if not libcxx:
            return

        compiler = settings.get_safe("compiler.base") or settings.get_safe("compiler")

        if compiler in ['clang', 'apple-clang']:
            if libcxx in ['libstdc++', 'libstdc++11']:
                return '-stdlib=libstdc++'
            elif libcxx == 'libc++':
                return '-stdlib=libc++'
        elif compiler == 'sun-cc':
            return ({"libCstd": "-library=Cstd",
                     "libstdcxx": "-library=stdcxx4",
                     "libstlport": "-library=stlport4",
                     "libstdc++": "-library=stdcpp"}.get(libcxx))
        elif compiler == "qcc":
            return "-Y _%s" % str(libcxx)

    def environment(self):
        env = Environment()
        # defines
        if self.ndebug:
            self.defines.append(self.ndebug)
        if self.gcc_cxx11_abi:
            self.defines.append(self.gcc_cxx11_abi)

        if self.libcxx:
            self.cxxflags.append(self.libcxx)

        if self.cppstd:
            self.cxxflags.append(self.cppstd)

        if self.arch_flag:
            self.cxxflags.append(self.arch_flag)
            self.cflags.append(self.arch_flag)
            self.ldflags.append(self.arch_flag)

        if self.build_type_flags:
            self.cxxflags.extend(self.build_type_flags)
            self.cflags.extend(self.build_type_flags)

        if self.build_type_link_flags:
            self.ldflags.extend(self.build_type_link_flags)

        if self.fpic:
            self.cxxflags.append("-fPIC")
            self.cflags.append("-fPIC")

        if self.msvc_runtime_flag:
            self.cxxflags.append(self.msvc_runtime_flag)
            self.cflags.append(self.msvc_runtime_flag)

        if is_msvc(self._conanfile):
            env.define("CXX", "cl")
            env.define("CC", "cl")

        # FIXME: Previously these flags where checked if already present at env 'CFLAGS', 'CXXFLAGS'
        #        and 'self.cxxflags', 'self.cflags' before adding them
        for f in list(filter(bool, [self.apple_isysroot_flag,
                                    self.apple_arch_flag,
                                    self.apple_min_version_flag])):
            self.cxxflags.append(f)
            self.cflags.append(f)
            self.ldflags.append(f)

        env.append("CPPFLAGS", ["-D{}".format(d) for d in self.defines])
        env.append("CXXFLAGS", self.cxxflags)
        env.append("CFLAGS", self.cflags)
        env.append("LDFLAGS", self.ldflags)
        return env

    def vars(self):
        return self.environment().vars(self._conanfile, scope="build")

    def generate(self, env=None, scope="build"):
        env = env or self.environment()
        env = env.vars(self._conanfile, scope=scope)
        env.save_script("conanautotoolstoolchain")
        self.generate_args()
        VCVars(self._conanfile).generate(scope=scope)

    def generate_args(self):
        configure_args = []
        configure_args.extend(self.configure_args)

        if self.default_configure_install_args and self._conanfile.package_folder:
            def _get_cpp_info_value(name):
                # Why not taking cpp.build? because this variables are used by the "cmake install"
                # that correspond to the package folder (even if the root is the build directory)
                elements = getattr(self._conanfile.cpp.package, name)
                return elements[0] if elements else None

            # If someone want arguments but not the defaults can pass them in args manually
            configure_args.extend(
                    ['--prefix=%s' % self._conanfile.package_folder.replace("\\", "/"),
                     "--bindir=${prefix}/%s" % _get_cpp_info_value("bindirs"),
                     "--sbindir=${prefix}/%s" % _get_cpp_info_value("bindirs"),
                     "--libdir=${prefix}/%s" % _get_cpp_info_value("libdirs"),
                     "--includedir=${prefix}/%s" % _get_cpp_info_value("includedirs"),
                     "--oldincludedir=${prefix}/%s" % _get_cpp_info_value("includedirs"),
                     "--datarootdir=${prefix}/%s" % _get_cpp_info_value("resdirs")])
        user_args_str = args_to_string(self.configure_args)
        for flag, var in (("host", self._host), ("build", self._build), ("target", self._target)):
            if var and flag not in user_args_str:
                configure_args.append('--{}={}'.format(flag, var))

        args = {"configure_args": args_to_string(configure_args),
                "make_args":  args_to_string(self.make_args)}

        save_toolchain_args(args, namespace=self._namespace)
