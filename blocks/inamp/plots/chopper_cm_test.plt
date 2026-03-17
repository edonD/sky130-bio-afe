set encoding utf8
set termoption noenhanced
set title "Chopper CM Rejection Test"
set xlabel "s"
set ylabel "V"
set grid
unset logscale x 
set xrange [0.000000e+00:1.000000e-01]
unset logscale y 
set yrange [-1.986721e+00:3.859551e-01]
#set xtics 1
#set x2tics 1
#set ytics 1
#set y2tics 1
set format y "%g"
set format x "%g"
plot 'plots/chopper_cm_test.data' using 1:2 with lines lw 1 title "vdiff_filt",\
'plots/chopper_cm_test.data' using 3:4 with lines lw 1 title "vdiff_raw"
set terminal push
set terminal png noenhanced
set out 'plots/chopper_cm_test.png'
replot
set term pop
replot
