"""
run.py - the file you run to start ScreenQA.

    python run.py                       start the app
    python run.py --self-test           check that every part works (nothing is sent online)
    python run.py --self-test --live    ...and also test one real AI answer

It is deliberately tiny: all real code lives in the "screenqa" package folder.
"""

import sys

# This "if" is true only when you run this file directly (not when it is imported).
if __name__ == "__main__":
    try:
        if "--self-test" in sys.argv:
            from screenqa.selftest import main as self_test

            sys.exit(self_test(sys.argv[1:]))

        from screenqa.app import main

        # main() returns 0 on a normal exit; sys.exit passes that number to Windows.
        sys.exit(main())
    except SystemExit:
        raise  # a normal exit, not an error
    except Exception as error:  # ScreenQA couldn't start: explain it instead of vanishing
        from screenqa.errors import report_startup_error

        report_startup_error(error)
        sys.exit(1)
