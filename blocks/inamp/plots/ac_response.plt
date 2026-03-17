set encoding utf8
set termoption noenhanced
set title "Diff Gain (dB)"
set xlabel "Hz"
set ylabel "dB"
set grid
set logscale x
set xrange [1e-02:1e+09]
set mxtics 10
set grid mxtics
unset logscale y 
set yrange [-4.933072e+00:3.777720e+01]
#set xtics 1
#set x2tics 1
#set ytics 1
#set y2tics 1
set format y "%g"
set format x "%g"
plot 'plots/ac_response.data' using 1:2 with lines lw 1 title "gain_db"
set terminal push
set terminal png noenhanced
set out 'plots/ac_response.png'
replot
set term pop
replot
